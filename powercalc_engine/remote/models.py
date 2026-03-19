"""Data models for remote profile operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RemoteFile:
    """Metadata for a single file in a remote profile directory."""

    name: str          # filename, e.g. "brightness.csv.gz"
    remote_path: str   # full path inside repo, e.g. "profile_library/signify/LCA001/brightness.csv.gz"
    sha: str           # Git blob SHA — used as fingerprint for update detection
    download_url: str  # Direct URL to raw file content


@dataclass
class DownloadResult:
    """Result returned by GithubProfileStore.download_profile()."""

    manufacturer: str
    model: str
    found_remote: bool
    downloaded: bool
    updated: bool                              # True when an existing local copy was refreshed
    local_path: Path | None
    linked_profiles_downloaded: list[str] = field(default_factory=list)  # "mfr/model" strings
    message: str = ""


@dataclass
class UpdateResult:
    """Result returned by GithubProfileStore.update_profile()."""

    manufacturer: str
    model: str
    had_local: bool
    was_current: bool       # True when nothing needed updating
    updated: bool           # True when files were actually refreshed
    files_changed: list[str] = field(default_factory=list)
    message: str = ""
