"""Brightness LUT - ``brightness.csv(.gz)``.

CSV schema (header required):
    bri,watt

Columns
-------
bri  : int, 0-255 - brightness level at which the measurement was taken.
watt : float (dot as decimal separator) - power draw at that brightness.

Lookup strategy
---------------
Linear interpolation on the ``bri`` axis.  See :func:`.base.interpolate_bri`.
"""

from __future__ import annotations

from pathlib import Path

from .base import interpolate_bri, open_lut_file, read_csv_rows

# Type alias for the in-memory LUT.
BrightnessLut = dict[int, float]  # bri -> watt


def load_brightness_lut(profile_path: Path) -> BrightnessLut:
    """Parse ``brightness.csv(.gz)`` from *profile_path* into a dict.

    Raises
    ------
    MissingLookupTableError
        When neither variant of the file exists.
    ValueError
        When a row cannot be parsed (malformed CSV, wrong decimal separator, …).
    """
    lut: BrightnessLut = {}

    with open_lut_file(profile_path, "brightness") as fh:
        for row in read_csv_rows(fh):
            bri = int(row[0])
            watt = float(row[1])
            lut[bri] = watt

    return lut


def get_brightness_power(lut: BrightnessLut, brightness: int) -> float:
    """Return interpolated watt for *brightness*.

    Parameters
    ----------
    lut        : Previously loaded :class:`BrightnessLut`.
    brightness : Target brightness value (0-255).
    """
    return interpolate_bri(lut, brightness)
