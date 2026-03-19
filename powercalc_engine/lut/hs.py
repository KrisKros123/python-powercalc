"""Hue-saturation LUT - ``hs.csv(.gz)``.

CSV schema (header required):
    bri,hue,sat,watt

Columns
-------
bri  : int, 0-255    - brightness level.
hue  : int, 0-65535  - hue.
sat  : int, 0-255    - saturation.
watt : float (dot)   - power draw.

Lookup strategy (mirrors original powercalc behaviour)
------------------------------------------------------
The in-memory structure is a three-level nested dict::

    bri → { hue → { sat → watt } }

1. **Brightness axis**: linear interpolation between surrounding sample
   points (same helper as all other LUTs).
2. **Hue axis**: nearest-neighbour, evaluated at each of the two surrounding
   brightness levels independently.
3. **Saturation axis**: nearest-neighbour, evaluated after hue selection.

Full lookup flow:
  a. Find *lower_bri* / *upper_bri* (or clamp).
  b. At *lower_bri*: nearest hue → nearest sat → ``watt_lower``.
  c. At *upper_bri*: nearest hue → nearest sat → ``watt_upper``.
  d. Linear interpolation between ``watt_lower`` and ``watt_upper``.
"""

from __future__ import annotations

from pathlib import Path

from .base import nearest_key, open_lut_file, read_csv_rows

# bri -> hue -> sat -> watt
HsLut = dict[int, dict[int, dict[int, float]]]


def load_hs_lut(profile_path: Path) -> HsLut:
    """Parse ``hs.csv(.gz)`` from *profile_path*.

    Raises
    ------
    MissingLookupTableError
        When neither variant of the file exists.
    ValueError
        When a row cannot be parsed.
    """
    lut: HsLut = {}

    with open_lut_file(profile_path, "hs") as fh:
        for row in read_csv_rows(fh):
            bri = int(row[0])
            hue = int(row[1])
            sat = int(row[2])
            watt = float(row[3])
            lut.setdefault(bri, {}).setdefault(hue, {})[sat] = watt

    return lut


def _watt_at_bri(
    hue_map: dict[int, dict[int, float]],
    hue: int,
    saturation: int,
) -> float:
    """Select watt using nearest-neighbour for hue then saturation."""
    sorted_hues = sorted(hue_map)
    best_hue = nearest_key(sorted_hues, hue)
    sat_map = hue_map[best_hue]
    sorted_sats = sorted(sat_map)
    best_sat = nearest_key(sorted_sats, saturation)
    return sat_map[best_sat]


def get_hs_power(
    lut: HsLut,
    brightness: int,
    hue: int,
    saturation: int,
) -> float:
    """Return interpolated watt for (*brightness*, *hue*, *saturation*).

    Parameters
    ----------
    lut        : Previously loaded :class:`HsLut`.
    brightness : Target brightness 0-255.
    hue        : Target hue 0-65535.
    saturation : Target saturation 0-255.
    """
    if not lut:
        return 0.0

    sorted_bri_keys = sorted(lut.keys())

    # --- Clamp to brightness boundaries -------------------------------------
    if brightness <= sorted_bri_keys[0]:
        return _watt_at_bri(lut[sorted_bri_keys[0]], hue, saturation)

    if brightness >= sorted_bri_keys[-1]:
        return _watt_at_bri(lut[sorted_bri_keys[-1]], hue, saturation)

    lower_bri = max(k for k in sorted_bri_keys if k <= brightness)
    upper_bri = min(k for k in sorted_bri_keys if k >= brightness)

    if lower_bri == upper_bri:
        return _watt_at_bri(lut[lower_bri], hue, saturation)

    # --- Resolve watt at each surrounding brightness level ------------------
    watt_lower = _watt_at_bri(lut[lower_bri], hue, saturation)
    watt_upper = _watt_at_bri(lut[upper_bri], hue, saturation)

    # --- Linear interpolation on brightness ---------------------------------
    ratio = (brightness - lower_bri) / (upper_bri - lower_bri)
    return watt_lower + ratio * (watt_upper - watt_lower)


def get_hs_power_multilinear(
    lut: HsLut,
    brightness: int,
    hue: int,
    saturation: int,
) -> float:
    """Trilinear interpolation for (*brightness*, *hue*, *saturation*).

    DEVIATION FROM ORIGINAL - uses full trilinear interpolation instead of
    nearest-neighbour on the hue and saturation axes.  See
    :func:`.interpolation.interpolate_3d_trilinear` for details.

    Parameters
    ----------
    lut        : Previously loaded :class:`HsLut`.
    brightness : Target brightness 0-255.
    hue        : Target hue 0-65535.
    saturation : Target saturation 0-255.
    """
    from .interpolation import interpolate_3d_trilinear
    return interpolate_3d_trilinear(lut, brightness, hue, saturation)
