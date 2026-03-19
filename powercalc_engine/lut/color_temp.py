"""Color-temperature LUT — ``color_temp.csv(.gz)``.

CSV schema (header required):
    bri,mired,watt

Columns
-------
bri   : int, 0-255 — brightness level.
mired : int — color temperature in mired (micro-reciprocal degrees).
watt  : float (dot as decimal separator) — power draw.

Lookup strategy (mirrors original powercalc behaviour)
------------------------------------------------------
1. Build a nested mapping: ``bri → {mired → watt}``.
2. For the **brightness** axis: linear interpolation between the two
   surrounding sample points (via :func:`.base.interpolate_bri`).
3. For the **mired** axis: nearest-neighbour selection at each brightness
   level before interpolation.

The interpolation is performed as follows:
  a. Find *lower_bri* and *upper_bri* — the surrounding sampled brightness
     levels (or clamp to boundaries).
  b. At *lower_bri* find the nearest mired key → ``watt_lower``.
  c. At *upper_bri* find the nearest mired key → ``watt_upper``.
  d. Linearly interpolate ``watt_lower`` and ``watt_upper`` by how far
     *brightness* sits between *lower_bri* and *upper_bri*.
"""

from __future__ import annotations

from pathlib import Path

from .base import interpolate_bri, nearest_key, open_lut_file, read_csv_rows

# Nested mapping: bri → {mired → watt}
ColorTempLut = dict[int, dict[int, float]]


def load_color_temp_lut(profile_path: Path) -> ColorTempLut:
    """Parse ``color_temp.csv(.gz)`` from *profile_path*.

    Raises
    ------
    MissingLookupTableError
        When neither variant of the file exists.
    ValueError
        When a row cannot be parsed.
    """
    lut: ColorTempLut = {}

    with open_lut_file(profile_path, "color_temp") as fh:
        for row in read_csv_rows(fh):
            bri = int(row[0])
            mired = int(row[1])
            watt = float(row[2])
            lut.setdefault(bri, {})[mired] = watt

    return lut


def get_color_temp_power(
    lut: ColorTempLut,
    brightness: int,
    color_temp: int,
) -> float:
    """Return interpolated watt for (*brightness*, *color_temp*).

    Parameters
    ----------
    lut         : Previously loaded :class:`ColorTempLut`.
    brightness  : Target brightness 0-255.
    color_temp  : Target color temperature in mired.
    """
    if not lut:
        return 0.0

    sorted_bri_keys = sorted(lut.keys())

    # --- Clamp / find surrounding brightness levels -------------------------
    if brightness <= sorted_bri_keys[0]:
        mired_map = lut[sorted_bri_keys[0]]
        best_mired = nearest_key(sorted(mired_map), color_temp)
        return mired_map[best_mired]

    if brightness >= sorted_bri_keys[-1]:
        mired_map = lut[sorted_bri_keys[-1]]
        best_mired = nearest_key(sorted(mired_map), color_temp)
        return mired_map[best_mired]

    lower_bri = max(k for k in sorted_bri_keys if k <= brightness)
    upper_bri = min(k for k in sorted_bri_keys if k >= brightness)

    if lower_bri == upper_bri:
        mired_map = lut[lower_bri]
        best_mired = nearest_key(sorted(mired_map), color_temp)
        return mired_map[best_mired]

    # --- Nearest-neighbour on mired at each brightness level ----------------
    lower_mired_map = lut[lower_bri]
    upper_mired_map = lut[upper_bri]

    lower_mired = nearest_key(sorted(lower_mired_map), color_temp)
    upper_mired = nearest_key(sorted(upper_mired_map), color_temp)

    watt_lower = lower_mired_map[lower_mired]
    watt_upper = upper_mired_map[upper_mired]

    # --- Linear interpolation on brightness ---------------------------------
    ratio = (brightness - lower_bri) / (upper_bri - lower_bri)
    return watt_lower + ratio * (watt_upper - watt_lower)
