"""Thin HTTP client for GitHub Contents API.

Uses only stdlib (urllib.request / urllib.error) — no third-party deps.

GitHub Contents API
-------------------
GET https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}

Response for a directory → JSON array of entries:
  [{name, path, sha, type, download_url, …}, …]

Response for a file → JSON object with same fields + "content" (base64).

We never decode the base64 content from the API; instead we download raw
files via the `download_url` (pointing to raw.githubusercontent.com), which
is simpler and avoids the 1 MB API limit per file.

Rate limiting
-------------
Unauthenticated requests are limited to 60/hour per IP.  If GITHUB_TOKEN is
set in the environment it is added as a Bearer token to push the limit to
5000/hour.  The client surfaces 403/429 as RemoteAccessError with a clear
message.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..exceptions import RemoteAccessError, RemoteProfileNotFoundError
from .models import RemoteFile

_API_BASE = "https://api.github.com"
_ACCEPT_JSON = "application/vnd.github+json"
_API_VERSION = "2022-11-28"

# Skip SSL verification in environments where certs may be missing.
# This is acceptable for a developer tool; production use should leave SSL on.
import ssl as _ssl
_SSL_CTX = _ssl.create_default_context()


def _build_headers() -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": _ACCEPT_JSON,
        "X-GitHub-Api-Version": _API_VERSION,
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str) -> Any:
    """Fetch *url* and return parsed JSON.

    Raises
    ------
    RemoteProfileNotFoundError : HTTP 404
    RemoteAccessError          : any other HTTP error or network failure
    """
    req = urllib.request.Request(url, headers=_build_headers())
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RemoteProfileNotFoundError(
                f"Remote path not found (404): {url}"
            ) from exc
        if exc.code in (403, 429):
            raise RemoteAccessError(
                f"GitHub API rate-limited or forbidden (HTTP {exc.code}). "
                "Set GITHUB_TOKEN env var to raise limits."
            ) from exc
        raise RemoteAccessError(
            f"GitHub API returned HTTP {exc.code} for {url}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RemoteAccessError(
            f"Network error accessing {url}: {exc.reason}"
        ) from exc


def _get_bytes(url: str) -> bytes:
    """Download raw bytes from *url*."""
    req = urllib.request.Request(url, headers=_build_headers())
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RemoteProfileNotFoundError(
                f"File not found (404): {url}"
            ) from exc
        raise RemoteAccessError(
            f"HTTP {exc.code} downloading {url}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RemoteAccessError(
            f"Network error downloading {url}: {exc.reason}"
        ) from exc


class GithubClient:
    """Minimal GitHub Contents API client."""

    def __init__(
        self,
        owner: str,
        repo: str,
        ref: str = "master",
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.ref = ref

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def path_exists(self, remote_path: str) -> bool:
        """Return True if *remote_path* exists in the repo (any type)."""
        url = self._contents_url(remote_path)
        try:
            _get_json(url)
            return True
        except RemoteProfileNotFoundError:
            return False

    def list_directory(self, remote_path: str) -> list[RemoteFile]:
        """Return a list of :class:`RemoteFile` entries for a directory.

        Raises
        ------
        RemoteProfileNotFoundError : path does not exist or is a file
        RemoteAccessError          : network / API error
        """
        url = self._contents_url(remote_path)
        data = _get_json(url)

        if not isinstance(data, list):
            # The API returns a dict for a single file.
            raise RemoteProfileNotFoundError(
                f"Expected a directory at {remote_path!r}, got a file."
            )

        files: list[RemoteFile] = []
        for entry in data:
            if entry.get("type") != "file":
                continue  # skip subdirectories (profiles are flat)
            files.append(
                RemoteFile(
                    name=entry["name"],
                    remote_path=entry["path"],
                    sha=entry["sha"],
                    download_url=entry["download_url"],
                )
            )
        return files

    def download_file(self, remote_file: RemoteFile) -> bytes:
        """Download and return raw bytes for *remote_file*."""
        return _get_bytes(remote_file.download_url)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _contents_url(self, path: str) -> str:
        return (
            f"{_API_BASE}/repos/{self.owner}/{self.repo}"
            f"/contents/{path}?ref={self.ref}"
        )
