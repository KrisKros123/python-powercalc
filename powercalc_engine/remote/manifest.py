"""Per-profile local manifest (.powercalc_source.json).

The manifest is written into each downloaded profile directory and tracks
enough information to detect when the remote copy has changed without
needing to re-download every file.

Schema
------
{
  "repo_owner": "bramstroker",
  "repo_name": "homeassistant-powercalc",
  "repo_ref": "master",
  "manufacturer": "signify",
  "model": "LCA001",
  "canonical_remote_path": "profile_library/signify/LCA001",
  "downloaded_at": "2026-03-19T12:00:00Z",
  "files": [
    {"relative_path": "brightness.csv.gz", "sha": "<git-blob-sha>"}
  ],
  "linked_profiles": ["signify/LCA002"]   // optional
}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..exceptions import InvalidModelJsonError

MANIFEST_FILENAME = ".powercalc_source.json"


def manifest_path(profile_dir: Path) -> Path:
    return profile_dir / MANIFEST_FILENAME


def write_manifest(
    profile_dir: Path,
    *,
    repo_owner: str,
    repo_name: str,
    repo_ref: str,
    manufacturer: str,
    model: str,
    canonical_remote_path: str,
    files: list[dict],          # [{"relative_path": str, "sha": str}]
    linked_profiles: list[str] | None = None,
) -> None:
    """Write (or overwrite) the manifest for a profile."""
    data = {
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "repo_ref": repo_ref,
        "manufacturer": manufacturer,
        "model": model,
        "canonical_remote_path": canonical_remote_path,
        "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
        "linked_profiles": linked_profiles or [],
    }
    profile_dir.mkdir(parents=True, exist_ok=True)
    manifest_path(profile_dir).write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def read_manifest(profile_dir: Path) -> dict | None:
    """Return the manifest dict, or None if it does not exist.

    Raises
    ------
    InvalidModelJsonError
        When the manifest file exists but cannot be parsed as valid JSON.
    """
    mp = manifest_path(profile_dir)
    if not mp.exists():
        return None
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidModelJsonError(
            f"Manifest at {mp} is not valid JSON: {exc}"
        ) from exc


def sha_map_from_manifest(manifest: dict) -> dict[str, str]:
    """Return {relative_path: sha} from a manifest dict."""
    return {f["relative_path"]: f["sha"] for f in manifest.get("files", [])}
