"""Shared helpers for all LUT implementations.

Interpolation strategy (mirrors the original powercalc implementation):
- **Brightness axis**: linear interpolation between the two surrounding sample
  points.  If the target falls below the minimum or above the maximum sampled
  brightness the boundary value is returned (clamping).
- **All other axes** (hue, saturation, mired, effect): nearest-neighbour
  selection — the key whose distance to the target is smallest is chosen.
"""

from __future__ import annotations

import csv
import gzip
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Generator

from ..exceptions import MissingLookupTableError


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


@contextmanager
def open_lut_file(profile_path: Path, mode: str) -> Generator[IO[str], None, None]:
    """Open the LUT file for *mode*, preferring the gzip-compressed variant.

    Resolution order: ``<mode>.csv.gz``  →  ``<mode>.csv``

    Yields a text-mode file object regardless of compression.

    Raises
    ------
    MissingLookupTableError
        When neither variant exists in *profile_path*.
    """
    gz_path = profile_path / f"{mode}.csv.gz"
    csv_path = profile_path / f"{mode}.csv"

    if gz_path.exists():
        # gzip.open in text mode returns a wrapper that behaves like a regular
        # text IO object and is compatible with csv.reader.
        with gzip.open(gz_path, "rt", newline="", encoding="utf-8") as fh:
            yield fh  # type: ignore[misc]
        return

    if csv_path.exists():
        with open(csv_path, newline="", encoding="utf-8") as fh:
            yield fh
        return

    raise MissingLookupTableError(
        f"No LUT file for mode '{mode}' found in {profile_path}. "
        f"Expected '{mode}.csv.gz' or '{mode}.csv'."
    )


# ---------------------------------------------------------------------------
# Interpolation helpers
# ---------------------------------------------------------------------------


def nearest_key(sorted_keys: list[int], target: int) -> int:
    """Return the key from *sorted_keys* nearest to *target*.

    When two keys are equidistant the lower one is preferred (stable
    behaviour regardless of Python version).
    """
    if not sorted_keys:
        raise ValueError("sorted_keys must not be empty")
    # Binary-search style: the optimal key is one of the two surrounding
    # *target* in the sorted list.
    lo, hi = 0, len(sorted_keys) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_keys[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    # lo is now the index of the first key >= target.
    if lo == 0:
        return sorted_keys[0]
    # Compare the candidate (sorted_keys[lo]) with its left neighbour.
    left = sorted_keys[lo - 1]
    right = sorted_keys[lo]
    return left if (target - left) <= (right - target) else right


def interpolate_bri(bri_to_watt: dict[int, float], brightness: int) -> float:
    """Linear interpolation of watt over the brightness axis.

    The function clamps: values below the minimum sampled brightness return
    the watt at the minimum; values above the maximum return the watt at the
    maximum.

    Parameters
    ----------
    bri_to_watt : Mapping of brightness sample → watt value.
    brightness  : Target brightness (0-255).
    """
    if not bri_to_watt:
        return 0.0

    keys = sorted(bri_to_watt)

    # Clamp to boundaries.
    if brightness <= keys[0]:
        return bri_to_watt[keys[0]]
    if brightness >= keys[-1]:
        return bri_to_watt[keys[-1]]

    # Find surrounding sample points.
    lower = keys[0]
    for k in keys:
        if k <= brightness:
            lower = k
        else:
            break
    upper_candidates = [k for k in keys if k > brightness]
    upper = upper_candidates[0]

    # Linear interpolation.
    ratio = (brightness - lower) / (upper - lower)
    return bri_to_watt[lower] + ratio * (bri_to_watt[upper] - bri_to_watt[lower])


def read_csv_rows(file_obj: IO[str]) -> list[list[str]]:
    """Read all non-empty rows from a CSV file, skipping the header row."""
    reader = csv.reader(file_obj)
    rows = list(reader)
    # First row is the header — skip it.
    return [row for row in rows[1:] if row]
