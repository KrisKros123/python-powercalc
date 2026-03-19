"""Tests for the remote profile store.

All network calls are mocked - no real HTTP requests are made.
The mock surface is GithubClient (replaced on store._client directly).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from powercalc_engine.exceptions import (
    InvalidModelJsonError,
    ProfileUpdateError,
    RemoteAccessError,
    RemoteProfileNotFoundError,
)
from powercalc_engine.remote.github_store import GithubProfileStore
from powercalc_engine.remote.manifest import (
    MANIFEST_FILENAME,
    read_manifest,
    sha_map_from_manifest,
    write_manifest,
)
from powercalc_engine.remote.models import DownloadResult, RemoteFile, UpdateResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BRIGHTNESS_CSV = b"bri,watt\n0,0.4\n128,9.0\n255,18.0\n"
MODEL_JSON_PLAIN = json.dumps({"standby_power": 0.3}).encode()
MODEL_JSON_WITH_LINK = json.dumps({
    "standby_power": 0.4,
    "linked_profile": "signify/LCA001",
}).encode()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> GithubProfileStore:
    return GithubProfileStore(
        profile_dir=tmp_path,
        repo_owner="bramstroker",
        repo_name="homeassistant-powercalc",
        repo_ref="master",
    )


def _remote_file(manufacturer: str, model: str, name: str, sha: str) -> RemoteFile:
    return RemoteFile(
        name=name,
        remote_path=f"profile_library/{manufacturer}/{model}/{name}",
        sha=sha,
        download_url=f"https://raw.example.com/{manufacturer}/{model}/{name}",
    )


def _patch_client(store: GithubProfileStore) -> MagicMock:
    """Replace store._client with a fresh MagicMock and return it."""
    mock = MagicMock()
    mock.path_exists.return_value = True
    mock.list_directory.return_value = []
    mock.download_file.return_value = b""
    store._client = mock
    return mock


def _make_profile_dir(
    tmp_path: Path,
    manufacturer: str,
    model: str,
    file_shas: dict[str, str],
    file_contents: dict[str, bytes] | None = None,
) -> Path:
    """Create a local profile directory with files and a manifest."""
    path = tmp_path / manufacturer / model
    path.mkdir(parents=True)
    if file_contents:
        for name, data in file_contents.items():
            (path / name).write_bytes(data)
    else:
        for name in file_shas:
            # Write valid JSON for model.json, dummy bytes for everything else.
            if name == "model.json":
                (path / name).write_bytes(MODEL_JSON_PLAIN)
            else:
                (path / name).write_bytes(b"dummy")
    write_manifest(
        path,
        repo_owner="bramstroker",
        repo_name="homeassistant-powercalc",
        repo_ref="master",
        manufacturer=manufacturer,
        model=model,
        canonical_remote_path=f"profile_library/{manufacturer}/{model}",
        files=[{"relative_path": n, "sha": s} for n, s in file_shas.items()],
    )
    return path


# ---------------------------------------------------------------------------
# profile_exists
# ---------------------------------------------------------------------------


class TestProfileExists:
    def test_returns_true_when_remote_exists(self, tmp_path):
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.path_exists.return_value = True
        assert store.profile_exists("signify", "LCA001") is True

    def test_returns_false_when_remote_absent(self, tmp_path):
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.path_exists.return_value = False       # explicit False
        assert store.profile_exists("signify", "UNKNOWN") is False

    def test_remote_error_propagates(self, tmp_path):
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.path_exists.side_effect = RemoteAccessError("timeout")
        with pytest.raises(RemoteAccessError):
            store.profile_exists("signify", "LCA001")


# ---------------------------------------------------------------------------
# has_local_profile
# ---------------------------------------------------------------------------


class TestHasLocalProfile:
    def test_true_when_directory_exists(self, tmp_path):
        (tmp_path / "signify" / "LCA001").mkdir(parents=True)
        assert _make_store(tmp_path).has_local_profile("signify", "LCA001") is True

    def test_false_when_absent(self, tmp_path):
        assert _make_store(tmp_path).has_local_profile("signify", "MISSING") is False


# ---------------------------------------------------------------------------
# download_profile - basic cases
# ---------------------------------------------------------------------------


class TestDownloadProfile:
    def _setup(
        self,
        tmp_path: Path,
        manufacturer: str = "signify",
        model: str = "LCA001",
        remote_files: list[RemoteFile] | None = None,
        content_map: dict[str, bytes] | None = None,
    ) -> tuple[GithubProfileStore, MagicMock]:
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        if remote_files is None:
            remote_files = [
                _remote_file(manufacturer, model, "model.json", "sha_m"),
                _remote_file(manufacturer, model, "brightness.csv.gz", "sha_b"),
            ]
        if content_map is None:
            content_map = {
                "model.json": MODEL_JSON_PLAIN,
                "brightness.csv.gz": BRIGHTNESS_CSV,
            }
        mock.list_directory.return_value = remote_files
        # Route by filename.
        mock.download_file.side_effect = lambda rf: content_map[rf.name]
        return store, mock

    def test_creates_files_locally(self, tmp_path):
        store, _ = self._setup(tmp_path)
        store.download_profile("signify", "LCA001")
        assert (tmp_path / "signify" / "LCA001" / "brightness.csv.gz").exists()
        assert (tmp_path / "signify" / "LCA001" / "model.json").exists()

    def test_writes_manifest(self, tmp_path):
        store, _ = self._setup(tmp_path)
        store.download_profile("signify", "LCA001")
        manifest = read_manifest(tmp_path / "signify" / "LCA001")
        assert manifest["manufacturer"] == "signify"
        assert manifest["model"] == "LCA001"
        assert manifest["repo_ref"] == "master"
        shas = sha_map_from_manifest(manifest)
        assert shas["brightness.csv.gz"] == "sha_b"
        assert shas["model.json"] == "sha_m"

    def test_result_local_path(self, tmp_path):
        store, _ = self._setup(tmp_path)
        result = store.download_profile("signify", "LCA001")
        assert result.local_path == tmp_path / "signify" / "LCA001"

    def test_result_found_remote_and_downloaded(self, tmp_path):
        store, _ = self._setup(tmp_path)
        result = store.download_profile("signify", "LCA001")
        assert result.found_remote is True
        assert result.downloaded is True

    def test_not_found_returns_not_found_result(self, tmp_path):
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.list_directory.side_effect = RemoteProfileNotFoundError("404")
        result = store.download_profile("signify", "NONEXISTENT")
        assert result.found_remote is False
        assert result.downloaded is False
        assert result.local_path is None

    def test_already_existed_sets_updated_flag(self, tmp_path):
        (tmp_path / "signify" / "LCA001").mkdir(parents=True)
        store, _ = self._setup(tmp_path)
        result = store.download_profile("signify", "LCA001")
        assert result.updated is True   # directory pre-existed

    def test_fresh_download_updated_is_false(self, tmp_path):
        store, _ = self._setup(tmp_path)
        result = store.download_profile("signify", "LCA001")
        assert result.updated is False  # directory did not pre-exist

    def test_remote_access_error_propagates(self, tmp_path):
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.list_directory.side_effect = RemoteAccessError("network failure")
        with pytest.raises(RemoteAccessError):
            store.download_profile("signify", "LCA001")


# ---------------------------------------------------------------------------
# download_profile - linked_profile
# ---------------------------------------------------------------------------


class TestDownloadProfileWithLink:
    def test_linked_profile_is_downloaded(self, tmp_path):
        """LCA002 links to LCA001; downloading LCA002 must also fetch LCA001."""
        store = _make_store(tmp_path)
        mock = _patch_client(store)

        # Remote file listings per profile.
        lca002_listing = [
            _remote_file("signify", "LCA002", "model.json", "sha_m2"),
        ]
        lca001_listing = [
            _remote_file("signify", "LCA001", "model.json", "sha_m1"),
            _remote_file("signify", "LCA001", "brightness.csv.gz", "sha_b1"),
        ]

        def list_dir(path: str) -> list[RemoteFile]:
            if "LCA002" in path:
                return lca002_listing
            if "LCA001" in path:
                return lca001_listing
            raise RemoteProfileNotFoundError(path)

        # Content keyed by full remote_path to avoid name collisions.
        content_by_path: dict[str, bytes] = {
            "profile_library/signify/LCA002/model.json": MODEL_JSON_WITH_LINK,
            "profile_library/signify/LCA001/model.json": MODEL_JSON_PLAIN,
            "profile_library/signify/LCA001/brightness.csv.gz": BRIGHTNESS_CSV,
        }

        mock.list_directory.side_effect = list_dir
        mock.download_file.side_effect = lambda rf: content_by_path[rf.remote_path]

        result = store.download_profile("signify", "LCA002")
        assert result.downloaded is True
        assert "signify/LCA001" in result.linked_profiles_downloaded
        assert (tmp_path / "signify" / "LCA001" / "brightness.csv.gz").exists()

    def test_broken_linked_profile_raises(self, tmp_path):
        store = _make_store(tmp_path)
        mock = _patch_client(store)

        lca002_listing = [_remote_file("signify", "LCA002", "model.json", "sha_m")]

        def list_dir(path: str) -> list[RemoteFile]:
            if "LCA002" in path:
                return lca002_listing
            raise RemoteProfileNotFoundError(path)   # LCA001 not found

        mock.list_directory.side_effect = list_dir
        mock.download_file.return_value = MODEL_JSON_WITH_LINK

        with pytest.raises(RemoteProfileNotFoundError, match="linked_profile"):
            store.download_profile("signify", "LCA002")

    def test_cycle_guard_prevents_infinite_loop(self, tmp_path):
        """model.json pointing to itself must not loop."""
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        self_link = json.dumps({"linked_profile": "signify/LCA001"}).encode()
        listing = [_remote_file("signify", "LCA001", "model.json", "sha_x")]
        mock.list_directory.return_value = listing
        mock.download_file.return_value = self_link

        result = store.download_profile("signify", "LCA001")
        assert result.downloaded is True
        # Should not crash; LCA001 is already in _visited when recursion fires.


# ---------------------------------------------------------------------------
# update_profile
# ---------------------------------------------------------------------------


class TestUpdateProfile:
    def test_up_to_date_returns_was_current(self, tmp_path):
        _make_profile_dir(tmp_path, "signify", "LCA001",
                          file_shas={"model.json": "sha_m", "brightness.csv.gz": "sha_b"})
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.list_directory.return_value = [
            _remote_file("signify", "LCA001", "model.json", "sha_m"),
            _remote_file("signify", "LCA001", "brightness.csv.gz", "sha_b"),
        ]
        result = store.update_profile("signify", "LCA001")
        assert result.was_current is True
        assert result.updated is False
        assert result.files_changed == []
        mock.download_file.assert_not_called()

    def test_changed_sha_triggers_download(self, tmp_path):
        _make_profile_dir(tmp_path, "signify", "LCA001",
                          file_shas={"model.json": "sha_m", "brightness.csv.gz": "old_sha"})
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.list_directory.return_value = [
            _remote_file("signify", "LCA001", "model.json", "sha_m"),
            _remote_file("signify", "LCA001", "brightness.csv.gz", "new_sha"),
        ]
        mock.download_file.return_value = BRIGHTNESS_CSV
        result = store.update_profile("signify", "LCA001")
        assert result.updated is True
        assert "brightness.csv.gz" in result.files_changed
        assert mock.download_file.call_count == 1

    def test_new_remote_file_triggers_download(self, tmp_path):
        _make_profile_dir(tmp_path, "signify", "LCA001",
                          file_shas={"model.json": "sha_m"})
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.list_directory.return_value = [
            _remote_file("signify", "LCA001", "model.json", "sha_m"),
            _remote_file("signify", "LCA001", "brightness.csv.gz", "sha_b"),  # new
        ]
        mock.download_file.return_value = BRIGHTNESS_CSV
        result = store.update_profile("signify", "LCA001")
        assert result.updated is True
        assert "brightness.csv.gz" in result.files_changed

    def test_no_local_profile_raises(self, tmp_path):
        store = _make_store(tmp_path)
        with pytest.raises(ProfileUpdateError, match="no local copy"):
            store.update_profile("signify", "MISSING")

    def test_manifest_shas_refreshed_after_update(self, tmp_path):
        _make_profile_dir(tmp_path, "signify", "LCA001",
                          file_shas={"model.json": "old_sha"})
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.list_directory.return_value = [
            _remote_file("signify", "LCA001", "model.json", "new_sha"),
        ]
        mock.download_file.return_value = MODEL_JSON_PLAIN
        store.update_profile("signify", "LCA001")
        manifest = read_manifest(tmp_path / "signify" / "LCA001")
        assert sha_map_from_manifest(manifest)["model.json"] == "new_sha"


# ---------------------------------------------------------------------------
# update_all_local_profiles
# ---------------------------------------------------------------------------


class TestUpdateAllLocalProfiles:
    def _seed(self, tmp_path: Path, profiles: list[tuple[str, str]]) -> None:
        for mfr, mdl in profiles:
            _make_profile_dir(tmp_path, mfr, mdl,
                               file_shas={"model.json": "sha1"})

    def test_updates_all_manifested_profiles(self, tmp_path):
        self._seed(tmp_path, [("signify", "LCA001"), ("signify", "LCA002")])
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.list_directory.return_value = [
            # SHAs match → no actual download needed.
            _remote_file("signify", "X", "model.json", "sha1"),
        ]
        results = store.update_all_local_profiles()
        assert len(results) == 2
        assert all(r.was_current for r in results)

    def test_skips_directories_without_manifest(self, tmp_path):
        (tmp_path / "signify" / "NOMANIFEST").mkdir(parents=True)
        self._seed(tmp_path, [("signify", "LCA001")])
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.list_directory.return_value = [
            _remote_file("signify", "LCA001", "model.json", "sha1"),
        ]
        results = store.update_all_local_profiles()
        assert len(results) == 1
        assert results[0].model == "LCA001"

    def test_empty_profile_dir_returns_empty_list(self, tmp_path):
        assert _make_store(tmp_path).update_all_local_profiles() == []

    def test_error_in_one_does_not_abort_others(self, tmp_path):
        self._seed(tmp_path, [("signify", "LCA001"), ("signify", "LCA002")])
        store = _make_store(tmp_path)
        mock = _patch_client(store)

        def list_dir(path: str) -> list[RemoteFile]:
            if "LCA001" in path:
                raise RemoteAccessError("simulated LCA001 failure")
            return [_remote_file("signify", "LCA002", "model.json", "sha1")]

        mock.list_directory.side_effect = list_dir
        results = store.update_all_local_profiles()
        assert len(results) == 2
        messages = [r.message for r in results]
        assert any("Error" in m for m in messages)
        assert any("up to date" in m for m in messages)


# ---------------------------------------------------------------------------
# ensure_profile_available
# ---------------------------------------------------------------------------


class TestEnsureProfileAvailable:
    def test_skips_download_if_already_local(self, tmp_path):
        (tmp_path / "signify" / "LCA001").mkdir(parents=True)
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        result = store.ensure_profile_available("signify", "LCA001")
        assert result.downloaded is False
        mock.list_directory.assert_not_called()

    def test_downloads_when_not_local(self, tmp_path):
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        listing = [_remote_file("signify", "LCA001", "model.json", "sha_m")]
        mock.list_directory.return_value = listing
        mock.download_file.return_value = MODEL_JSON_PLAIN
        result = store.ensure_profile_available("signify", "LCA001")
        assert result.downloaded is True


# ---------------------------------------------------------------------------
# Manifest module unit tests
# ---------------------------------------------------------------------------


class TestManifest:
    def test_roundtrip(self, tmp_path):
        write_manifest(
            tmp_path,
            repo_owner="bramstroker",
            repo_name="homeassistant-powercalc",
            repo_ref="master",
            manufacturer="signify",
            model="LCA001",
            canonical_remote_path="profile_library/signify/LCA001",
            files=[{"relative_path": "brightness.csv.gz", "sha": "abc123"}],
            linked_profiles=["signify/LCA002"],
        )
        manifest = read_manifest(tmp_path)
        assert manifest["manufacturer"] == "signify"
        assert manifest["linked_profiles"] == ["signify/LCA002"]
        assert sha_map_from_manifest(manifest) == {"brightness.csv.gz": "abc123"}

    def test_read_returns_none_when_absent(self, tmp_path):
        assert read_manifest(tmp_path) is None

    def test_read_raises_on_bad_json(self, tmp_path):
        (tmp_path / MANIFEST_FILENAME).write_text("not json", encoding="utf-8")
        with pytest.raises(InvalidModelJsonError):
            read_manifest(tmp_path)


# ---------------------------------------------------------------------------
# Error scenarios
# ---------------------------------------------------------------------------


class TestErrorScenarios:
    def test_http_500_propagates_as_remote_access_error(self, tmp_path):
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        mock.list_directory.side_effect = RemoteAccessError("HTTP 500")
        with pytest.raises(RemoteAccessError):
            store.download_profile("signify", "LCA001")

    def test_invalid_local_model_json_raises_on_download(self, tmp_path):
        """If downloaded model.json is not valid JSON, extracting linked_profile raises."""
        store = _make_store(tmp_path)
        mock = _patch_client(store)
        listing = [_remote_file("signify", "LCA001", "model.json", "sha_bad")]
        mock.list_directory.return_value = listing
        mock.download_file.return_value = b"not json at all"
        with pytest.raises(InvalidModelJsonError):
            store.download_profile("signify", "LCA001")
