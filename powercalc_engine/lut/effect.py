"""Effect LUT - ``effect.csv(.gz)``.

CSV schema (header required):
    effect,bri,watt

Columns
-------
effect : str  - name of the light effect as reported by HA (e.g. "candle").
bri    : int, 0-255 - brightness level at which the measurement was taken.
watt   : float (dot) - power draw.

Lookup strategy (mirrors original powercalc behaviour)
------------------------------------------------------
1. Build a nested mapping: ``effect_name → {bri → watt}``.
2. **Effect name**: exact string match (case-sensitive, matching HA attribute).
   If the name is absent a :class:`.exceptions.LutCalculationError` is raised.
3. **Brightness axis**: linear interpolation (same as other LUTs).
"""

from __future__ import annotations

import warnings
from pathlib import Path

from ..exceptions import LutCalculationError
from .base import interpolate_bri, open_lut_file, read_csv_rows

# effect_name -> {bri -> watt}
EffectLut = dict[str, dict[int, float]]


def load_effect_lut(profile_path: Path) -> EffectLut:
    """Parse ``effect.csv(.gz)`` from *profile_path*.

    Raises
    ------
    MissingLookupTableError
        When neither variant of the file exists.
    ValueError
        When a row cannot be parsed.
    """
    lut: EffectLut = {}

    with open_lut_file(profile_path, "effect") as fh:
        for row in read_csv_rows(fh):
            effect_name = row[0]
            bri = int(row[1])
            watt = float(row[2])
            lut.setdefault(effect_name, {})[bri] = watt

    return lut


def get_effect_power(
    lut: EffectLut,
    effect_name: str,
    brightness: int,
) -> float:
    """Return interpolated watt for (*effect_name*, *brightness*).

    Parameters
    ----------
    lut         : Previously loaded :class:`EffectLut`.
    effect_name : Exact name of the active effect.
    brightness  : Target brightness 0-255.

    Raises
    ------
    LutCalculationError
        When *effect_name* is not present in the LUT.
    """
    if effect_name not in lut:
        # DEVIATION FROM ORIGINAL: the original emits a logger warning and
        # returns None.  We raise an explicit exception so callers can decide
        # whether to fall through to another mode or propagate the error.
        raise LutCalculationError(
            f"Effect '{effect_name}' not found in effect LUT. "
            f"Available effects: {sorted(lut.keys())}"
        )

    return interpolate_bri(lut[effect_name], brightness)
