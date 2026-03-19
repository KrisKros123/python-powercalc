"""Profile loader - discovers profile directories and builds ModelProfile objects.

Profile resolution order
------------------------
1. Exact directory match: ``<profile_dir>/<manufacturer>/<model>``
2. Case-insensitive match on manufacturer + model directory names.
3. Alias scan: iterate model.json files in the matching manufacturer directory
   and check the ``aliases`` list for a match.
   Only InvalidModelJsonError is re-raised; missing/unreadable model.json
   files are silently skipped during the alias scan (the directory simply has
   no aliases to offer).

linked_profile resolution
--------------------------
When model.json contains ``linked_profile``, ``load_profile`` follows the
chain recursively so that A → B → C is fully resolved.  Each hop increments
``_depth``; exceeding ``_MAX_LINK_DEPTH`` raises ``ModelNotFoundError`` to
prevent infinite loops.

The LUT files (CSV/CSV.GZ) and ``available_modes`` are taken from the
*terminal* profile in the chain.  ``standby_power``, ``aliases``, and other
metadata always come from the *first* (requested) model's own model.json.
"""

from __future__ import annotations

from pathlib import Path

from .exceptions import InvalidModelJsonError, ModelNotFoundError
from .model_json import (
    extract_aliases,
    extract_linked_profile,
    extract_standby_power,
    load_model_json,
)
from .models import ModelProfile

_LUT_MODES: tuple[str, ...] = ("brightness", "color_temp", "hs", "effect")
_MAX_LINK_DEPTH = 5


# ---------------------------------------------------------------------------
# Directory resolution
# ---------------------------------------------------------------------------


def find_profile_path(
    profile_dir: Path,
    manufacturer: str,
    model: str,
) -> tuple[Path, str]:
    """Resolve the profile directory for *manufacturer*/*model*.

    Returns
    -------
    (path, canonical_model)
        ``path`` is the absolute profile directory.
        ``canonical_model`` is the actual on-disk directory name (may differ
        from *model* when an alias or different casing was used).

    Resolution order
    ----------------
    1. Exact match.
    2. Case-insensitive manufacturer + exact model.
    3. Case-insensitive manufacturer + case-insensitive model.
    4. Alias scan within the matched manufacturer directory.

    Raises
    ------
    ModelNotFoundError
        When no matching directory is found.
    """
    # 1. Exact match.
    exact = profile_dir / manufacturer / model
    if exact.is_dir():
        return exact, model

    mfr_lower = manufacturer.lower()
    model_lower = model.lower()

    # Find the manufacturer directory (case-insensitive).
    matched_mfr_dir: Path | None = None
    for d in sorted(profile_dir.iterdir()):
        if d.is_dir() and d.name.lower() == mfr_lower:
            matched_mfr_dir = d
            break

    if matched_mfr_dir is None:
        raise ModelNotFoundError(
            f"No profile found for manufacturer={manufacturer!r}, model={model!r} "
            f"under {profile_dir}"
        )

    # 2. Exact model name under the (possibly differently-cased) mfr dir.
    model_exact = matched_mfr_dir / model
    if model_exact.is_dir():
        return model_exact, model

    # 3 + 4. Case-insensitive model name scan *and* alias scan in one pass.
    alias_match: tuple[Path, str] | None = None

    for model_dir in sorted(matched_mfr_dir.iterdir()):
        if not model_dir.is_dir():
            continue

        # 3. Case-insensitive directory name.
        if model_dir.name.lower() == model_lower:
            return model_dir, model_dir.name

        # 4. Alias check.
        if alias_match is None:
            try:
                meta = load_model_json(model_dir)
            except InvalidModelJsonError:
                # Re-raise: a *present but broken* model.json should not be
                # silently swallowed - it signals a data problem in the library.
                raise
            except OSError:
                # Unreadable directory entry - skip quietly.
                continue
            aliases = extract_aliases(meta)
            if any(a.lower() == model_lower for a in aliases):
                alias_match = (model_dir, model_dir.name)

    if alias_match is not None:
        return alias_match

    raise ModelNotFoundError(
        f"No profile found for manufacturer={manufacturer!r}, model={model!r} "
        f"(including aliases) under {profile_dir}"
    )


def _detect_available_modes(profile_path: Path) -> set[str]:
    modes: set[str] = set()
    for mode in _LUT_MODES:
        if (
            (profile_path / f"{mode}.csv").exists()
            or (profile_path / f"{mode}.csv.gz").exists()
        ):
            modes.add(mode)
    return modes


def _resolve_linked_path(
    profile_dir: Path,
    own_manufacturer: str,
    linked_value: str,
) -> tuple[Path, str, str]:
    """Resolve a linked_profile string → (path, manufacturer, canonical_model).

    Formats accepted: ``"manufacturer/model"`` or ``"model"`` (same mfr).
    """
    if "/" in linked_value:
        linked_mfr, linked_model = linked_value.split("/", 1)
    else:
        linked_mfr = own_manufacturer
        linked_model = linked_value

    path, canonical = find_profile_path(profile_dir, linked_mfr, linked_model)
    return path, linked_mfr, canonical


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_profile(
    profile_dir: Path,
    manufacturer: str,
    model: str,
    _depth: int = 0,
    _root_metadata: dict | None = None,
) -> ModelProfile:
    """Load a :class:`ModelProfile` for *manufacturer*/*model*.

    Follows ``linked_profile`` chains recursively.  The metadata
    (standby_power, aliases, linked_profile string) is always taken from the
    *root* model's own model.json; only ``path`` and ``available_modes`` come
    from the terminal profile in the chain.

    Parameters
    ----------
    profile_dir     : Root of the profile library.
    manufacturer    : Manufacturer name (case-insensitive).
    model           : Model name or alias (case-insensitive).
    _depth          : Internal recursion depth counter (do not pass manually).
    _root_metadata  : Metadata from the root model, carried through the chain.

    Raises
    ------
    ModelNotFoundError
        When the directory is not found or the chain exceeds _MAX_LINK_DEPTH.
    InvalidModelJsonError
        When model.json is malformed.
    """
    if _depth > _MAX_LINK_DEPTH:
        raise ModelNotFoundError(
            f"linked_profile chain exceeds maximum depth ({_MAX_LINK_DEPTH}) "
            f"starting from {manufacturer}/{model}"
        )

    own_path, canonical_model = find_profile_path(profile_dir, manufacturer, model)

    # Root metadata is only loaded once (at depth 0); deeper hops reuse it.
    if _root_metadata is None:
        _root_metadata = load_model_json(own_path)

    # Use root metadata for all user-visible fields.
    standby_power = extract_standby_power(_root_metadata)
    aliases = extract_aliases(_root_metadata)
    linked_value = extract_linked_profile(_root_metadata if _depth == 0 else load_model_json(own_path))

    # Follow the chain if this node itself has a linked_profile.
    if linked_value:
        try:
            linked_path, linked_mfr, _ = _resolve_linked_path(
                profile_dir, manufacturer, linked_value
            )
        except ModelNotFoundError as exc:
            raise ModelNotFoundError(
                f"Profile {manufacturer}/{model} has linked_profile={linked_value!r} "
                f"which cannot be resolved: {exc}"
            ) from exc

        # Recurse into the linked profile to keep following any further chain.
        # We pass _root_metadata so standby_power etc. always come from depth-0.
        inner = load_profile(
            profile_dir,
            linked_mfr,
            linked_value.split("/")[-1] if "/" in linked_value else linked_value,
            _depth=_depth + 1,
            _root_metadata=_root_metadata,
        )
        lut_path = inner.path
        available_modes = inner.available_modes
    else:
        lut_path = own_path
        available_modes = _detect_available_modes(own_path)

    # requested_model = what the caller originally passed (at depth 0) or what
    # this recursive call was given.
    return ModelProfile(
        manufacturer=manufacturer,
        requested_model=model,
        canonical_model=canonical_model,
        path=lut_path,
        standby_power=standby_power,
        available_modes=available_modes,
        aliases=aliases,
        linked_profile=extract_linked_profile(_root_metadata) if _depth == 0 else None,
        metadata=_root_metadata if _depth == 0 else {},
    )
