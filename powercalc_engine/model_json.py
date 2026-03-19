"""Parsing and loading of model.json files from profile directories.

Relevant fields
---------------
standby_power   : float  - power draw in standby/off state.
aliases         : list   - alternative model identifiers for lookup.
linked_profile  : str    - "manufacturer/model" redirect to another profile's
                           LUT files (same manufacturer when no slash given).
                           Source: PowerProfile.linked_profile in
                           custom_components/powercalc/power_profile/profile.py
"""

from __future__ import annotations

import json
from pathlib import Path

from .exceptions import InvalidModelJsonError

_FLOAT_FIELDS = ("standby_power",)


def load_model_json(profile_path: Path) -> dict:
    """Parse model.json from *profile_path* directory.

    Returns an empty dict when model.json does not exist.

    Raises
    ------
    InvalidModelJsonError
        When the file exists but cannot be parsed or contains a bad type.
    """
    json_path = profile_path / "model.json"

    if not json_path.exists():
        return {}

    try:
        with open(json_path, encoding="utf-8") as fh:
            data: dict = json.load(fh)
    except json.JSONDecodeError as exc:
        raise InvalidModelJsonError(
            f"Invalid JSON in {json_path}: {exc}"
        ) from exc
    except OSError as exc:
        raise InvalidModelJsonError(f"Cannot read {json_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise InvalidModelJsonError(
            f"{json_path} must contain a JSON object, got {type(data).__name__}"
        )

    for f in _FLOAT_FIELDS:
        if f in data:
            raw = data[f]
            if raw is None:
                continue
            try:
                data[f] = float(raw)
            except (TypeError, ValueError) as exc:
                raise InvalidModelJsonError(
                    f"Field '{f}' in {json_path} must be numeric, got {raw!r}"
                ) from exc

    return data


def extract_standby_power(metadata: dict) -> float | None:
    value = metadata.get("standby_power")
    if value is None:
        return None
    return float(value)


def extract_aliases(metadata: dict) -> list[str]:
    """Return the list of model aliases from *metadata*.

    Accepts a JSON array or a single string.  Returns [] when absent.
    Source: ProfileLibrary._get_aliases() in the original codebase.
    """
    raw = metadata.get("aliases")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if item is not None]
    return []


def extract_linked_profile(metadata: dict) -> str | None:
    """Return the linked_profile value from *metadata* or None.

    The value is a string "manufacturer/model" or just "model" (same mfr).
    Source: PowerProfile.linked_profile in the original codebase.
    """
    value = metadata.get("linked_profile")
    if not value or not isinstance(value, str):
        return None
    return value.strip()
