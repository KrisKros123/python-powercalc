"""GithubProfileStore — on-demand profile downloader and updater.

Design contract
---------------
- Reads nothing from PowercalcEngine internals.
- Writes only to ``profile_dir`` on the local filesystem.
- Network I/O is isolated in GithubClient.
- All remote paths are under ``profile_library/`` in the source repo.
- One manifest file (``.powercalc_source.json``) is written per profile.

linked_profile resolution
--------------------------
After downloading model.json for a profile, the store parses it for a
``linked_profile`` field and downloads the referenced profile automatically.
The linked_profiles list in the manifest records which links were followed so
that update_all_local_profiles can also update them.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..exceptions import (
    InvalidModelJsonError,
    ProfileUpdateError,
    RemoteAccessError,
    RemoteProfileNotFoundError,
)
from ..model_json import extract_linked_profile
from .github_client import GithubClient
from .manifest import (
    read_manifest,
    sha_map_from_manifest,
    write_manifest,
)
from .models import DownloadResult, RemoteFile, UpdateResult

# Root directory inside the repo that holds all profile data.
_PROFILE_LIBRARY_ROOT = "profile_library"


class GithubProfileStore:
    """Download and update powercalc profiles from GitHub on-demand.

    Parameters
    ----------
    profile_dir  : Local directory where profiles are stored.
                   Corresponds to the ``profile_dir`` of PowercalcEngine.
    repo_owner   : GitHub repository owner.
    repo_name    : GitHub repository name.
    repo_ref     : Branch, tag, or commit SHA.  Defaults to ``"master"``
                   (confirmed default branch of bramstroker/homeassistant-powercalc).
    """

    def __init__(
        self,
        profile_dir: str | Path,
        repo_owner: str = "bramstroker",
        repo_name: str = "homeassistant-powercalc",
        repo_ref: str = "master",
    ) -> None:
        self._profile_dir = Path(profile_dir)
        self._repo_owner = repo_owner
        self._repo_name = repo_name
        self._repo_ref = repo_ref
        self._client = GithubClient(
            owner=repo_owner,
            repo=repo_name,
            ref=repo_ref,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def profile_exists(self, manufacturer: str, model: str) -> bool:
        """Return True if the profile exists in the remote repository.

        Does NOT require a local copy.  Makes one HTTP HEAD-equivalent call
        via the GitHub Contents API.
        """
        remote_path = self._remote_path(manufacturer, model)
        return self._client.path_exists(remote_path)

    def has_local_profile(self, manufacturer: str, model: str) -> bool:
        """Return True if a local copy of the profile directory exists."""
        return self._local_path(manufacturer, model).is_dir()

    def download_profile(
        self,
        manufacturer: str,
        model: str,
        _visited: set[str] | None = None,
    ) -> DownloadResult:
        """Download *manufacturer/model* from GitHub to the local profile_dir.

        If model.json contains ``linked_profile`` the linked profile is also
        downloaded (recursively, guarded against cycles by ``_visited``).

        Returns a :class:`DownloadResult` describing what happened.

        Raises
        ------
        RemoteProfileNotFoundError : profile does not exist on GitHub.
        RemoteAccessError          : network / API error.
        InvalidModelJsonError      : model.json on GitHub is malformed.
        """
        if _visited is None:
            _visited = set()

        key = f"{manufacturer}/{model}"
        if key in _visited:
            # Cycle guard — return a no-op result.
            return DownloadResult(
                manufacturer=manufacturer,
                model=model,
                found_remote=False,
                downloaded=False,
                updated=False,
                local_path=None,
                message=f"Skipped (already visited in this chain): {key}",
            )
        _visited.add(key)

        remote_path = self._remote_path(manufacturer, model)
        local_path = self._local_path(manufacturer, model)
        already_existed = local_path.is_dir()

        # Fetch directory listing — raises RemoteProfileNotFoundError if absent.
        try:
            remote_files = self._client.list_directory(remote_path)
        except RemoteProfileNotFoundError:
            return DownloadResult(
                manufacturer=manufacturer,
                model=model,
                found_remote=False,
                downloaded=False,
                updated=False,
                local_path=None,
                message=f"Profile not found in remote repository: {key}",
            )

        # Download all files.
        local_path.mkdir(parents=True, exist_ok=True)
        file_records: list[dict] = []
        for rf in remote_files:
            data = self._client.download_file(rf)
            (local_path / rf.name).write_bytes(data)
            file_records.append({"relative_path": rf.name, "sha": rf.sha})

        # Parse model.json for linked_profile.
        linked_profiles_downloaded: list[str] = []
        linked_value = self._extract_linked_from_local(local_path)
        if linked_value:
            linked_mfr, linked_model = self._parse_linked_value(
                linked_value, manufacturer
            )
            linked_key = f"{linked_mfr}/{linked_model}"
            if linked_key not in _visited:
                linked_result = self.download_profile(
                    linked_mfr, linked_model, _visited=_visited
                )
                if linked_result.found_remote or linked_result.downloaded:
                    linked_profiles_downloaded.append(linked_key)
                elif not linked_result.found_remote:
                    raise RemoteProfileNotFoundError(
                        f"Profile {key} has linked_profile={linked_value!r} "
                        f"but {linked_key!r} was not found in the remote repository."
                    )
                # Collect any transitive links too.
                linked_profiles_downloaded.extend(
                    linked_result.linked_profiles_downloaded
                )

        # Write manifest.
        write_manifest(
            local_path,
            repo_owner=self._repo_owner,
            repo_name=self._repo_name,
            repo_ref=self._repo_ref,
            manufacturer=manufacturer,
            model=model,
            canonical_remote_path=remote_path,
            files=file_records,
            linked_profiles=linked_profiles_downloaded,
        )

        return DownloadResult(
            manufacturer=manufacturer,
            model=model,
            found_remote=True,
            downloaded=True,
            updated=already_existed,
            local_path=local_path,
            linked_profiles_downloaded=linked_profiles_downloaded,
            message=(
                f"Updated existing profile {key}."
                if already_existed
                else f"Downloaded profile {key}."
            ),
        )

    def update_profile(
        self,
        manufacturer: str,
        model: str,
    ) -> UpdateResult:
        """Check and apply updates for a locally cached profile.

        Compares the Git blob SHA of each remote file against the value stored
        in the local manifest.  Only downloads files that have changed.

        Raises
        ------
        ProfileUpdateError         : profile does not exist locally.
        RemoteAccessError          : network / API error.
        RemoteProfileNotFoundError : profile no longer exists on GitHub.
        """
        key = f"{manufacturer}/{model}"
        local_path = self._local_path(manufacturer, model)

        if not local_path.is_dir():
            raise ProfileUpdateError(
                f"Cannot update {key}: no local copy found. "
                "Use download_profile() first."
            )

        manifest = read_manifest(local_path)
        local_shas = sha_map_from_manifest(manifest) if manifest else {}

        remote_path = self._remote_path(manufacturer, model)
        remote_files = self._client.list_directory(remote_path)

        changed: list[str] = []
        for rf in remote_files:
            if local_shas.get(rf.name) != rf.sha:
                changed.append(rf.name)

        # Also detect locally-missing files (new files added upstream).
        remote_names = {rf.name for rf in remote_files}
        for name in remote_names:
            if not (local_path / name).exists() and name not in changed:
                changed.append(name)

        if not changed:
            return UpdateResult(
                manufacturer=manufacturer,
                model=model,
                had_local=True,
                was_current=True,
                updated=False,
                files_changed=[],
                message=f"Profile {key} is up to date.",
            )

        # Download changed files.
        file_records: list[dict] = []
        changed_set = set(changed)
        for rf in remote_files:
            if rf.name in changed_set:
                data = self._client.download_file(rf)
                (local_path / rf.name).write_bytes(data)
            file_records.append({"relative_path": rf.name, "sha": rf.sha})

        # Refresh manifest.
        linked_value = self._extract_linked_from_local(local_path)
        linked_profiles = (
            [self._linked_key(linked_value, manufacturer)]
            if linked_value
            else []
        )
        write_manifest(
            local_path,
            repo_owner=self._repo_owner,
            repo_name=self._repo_name,
            repo_ref=self._repo_ref,
            manufacturer=manufacturer,
            model=model,
            canonical_remote_path=remote_path,
            files=file_records,
            linked_profiles=linked_profiles,
        )

        return UpdateResult(
            manufacturer=manufacturer,
            model=model,
            had_local=True,
            was_current=False,
            updated=True,
            files_changed=changed,
            message=f"Updated {len(changed)} file(s) in {key}: {', '.join(changed)}",
        )

    def update_all_local_profiles(self) -> list[UpdateResult]:
        """Update all profiles that have a local manifest.

        Scans ``profile_dir`` for ``.powercalc_source.json`` files and calls
        :meth:`update_profile` for each one found.  Does NOT download new
        profiles; only refreshes already-local ones.
        """
        results: list[UpdateResult] = []
        if not self._profile_dir.is_dir():
            return results

        for mfr_dir in sorted(self._profile_dir.iterdir()):
            if not mfr_dir.is_dir():
                continue
            for model_dir in sorted(mfr_dir.iterdir()):
                if not model_dir.is_dir():
                    continue
                manifest_file = model_dir / ".powercalc_source.json"
                if not manifest_file.exists():
                    continue
                manifest = read_manifest(model_dir)
                if not manifest:
                    continue
                mfr = manifest.get("manufacturer", mfr_dir.name)
                mdl = manifest.get("model", model_dir.name)
                try:
                    result = self.update_profile(mfr, mdl)
                except (RemoteAccessError, RemoteProfileNotFoundError, ProfileUpdateError) as exc:
                    results.append(UpdateResult(
                        manufacturer=mfr,
                        model=mdl,
                        had_local=True,
                        was_current=False,
                        updated=False,
                        message=f"Error: {exc}",
                    ))
                    continue
                results.append(result)

        return results

    def ensure_profile_available(
        self,
        manufacturer: str,
        model: str,
    ) -> DownloadResult:
        """Download the profile only if it is not already local.

        Convenience method for use alongside :class:`PowercalcEngine`:

        >>> store.ensure_profile_available("signify", "LCA001")
        >>> engine.get_power("signify", "LCA001", state={...})
        """
        if self.has_local_profile(manufacturer, model):
            return DownloadResult(
                manufacturer=manufacturer,
                model=model,
                found_remote=False,
                downloaded=False,
                updated=False,
                local_path=self._local_path(manufacturer, model),
                message="Profile already available locally.",
            )
        return self.download_profile(manufacturer, model)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _remote_path(self, manufacturer: str, model: str) -> str:
        return f"{_PROFILE_LIBRARY_ROOT}/{manufacturer}/{model}"

    def _local_path(self, manufacturer: str, model: str) -> Path:
        return self._profile_dir / manufacturer / model

    def _extract_linked_from_local(self, profile_dir: Path) -> str | None:
        """Read linked_profile from a local model.json; return None if absent."""
        model_json_path = profile_dir / "model.json"
        if not model_json_path.exists():
            return None
        try:
            data = json.loads(model_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InvalidModelJsonError(
                f"model.json in {profile_dir} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(data, dict):
            return None
        return extract_linked_profile(data)

    @staticmethod
    def _parse_linked_value(
        linked_value: str, own_manufacturer: str
    ) -> tuple[str, str]:
        """Split 'manufacturer/model' or 'model' into (manufacturer, model)."""
        if "/" in linked_value:
            mfr, mdl = linked_value.split("/", 1)
            return mfr, mdl
        return own_manufacturer, linked_value

    @staticmethod
    def _linked_key(linked_value: str, own_manufacturer: str) -> str:
        if "/" in linked_value:
            return linked_value
        return f"{own_manufacturer}/{linked_value}"
