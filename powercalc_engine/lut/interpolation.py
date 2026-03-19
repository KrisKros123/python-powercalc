"""Multi-dimensional interpolation helpers for LUT lookup.

DEVIATION FROM ORIGINAL - this entire module is new.  The original powercalc
uses nearest-neighbour for all axes except brightness (which is linear).  This
module adds optional bilinear (2-D) and trilinear (3-D) interpolation that can
be selected via ``PowercalcEngine(interpolation_mode="multilinear")``.

Helpers
-------
lerp(a, b, t)
    Basic linear interpolation.

_find_bracket(sorted_keys, target)
    Locate the surrounding pair of sample keys for a target value.
    Returns (lower, upper, t) where t ∈ [0, 1].
    Clamps when target is outside the sampled range.

interpolate_2d_bilinear(lut_2d, x, y)
    Bilinear interpolation over a nested dict {x: {y: watt}}.
    Used for color_temp (bri × mired).

interpolate_3d_trilinear(lut_3d, x, y, z)
    Trilinear interpolation over a nested dict {x: {y: {z: watt}}}.
    Used for hs (bri × hue × sat).

Fallback strategy
-----------------
If any axis has fewer than two distinct sample points (e.g. a profile only
measured one hue level), that axis falls back to nearest-neighbour.  The
caller never needs to guard against degenerate LUTs.
"""

from __future__ import annotations

from .base import nearest_key


# ---------------------------------------------------------------------------
# Primitive
# ---------------------------------------------------------------------------


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation:  a + t * (b - a),  t clamped to [0, 1]."""
    t = max(0.0, min(1.0, t))
    return a + t * (b - a)


# ---------------------------------------------------------------------------
# Bracket finder
# ---------------------------------------------------------------------------


def _find_bracket(
    sorted_keys: list[int],
    target: int,
) -> tuple[int, int, float]:
    """Return ``(lower, upper, t)`` for *target* within *sorted_keys*.

    *t* is the fraction of the way from *lower* to *upper* in [0, 1].

    Clamping behaviour
    ------------------
    - target ≤ min(keys)  →  (min, min, 0.0)
    - target ≥ max(keys)  →  (max, max, 0.0)
    - exact key hit        →  (key, key, 0.0)

    When lower == upper lerp(a, b, 0.0) == a, so the maths stays consistent.
    """
    if not sorted_keys:
        raise ValueError("sorted_keys must not be empty")

    if target <= sorted_keys[0]:
        return sorted_keys[0], sorted_keys[0], 0.0

    if target >= sorted_keys[-1]:
        return sorted_keys[-1], sorted_keys[-1], 0.0

    # Find the tightest bracket.
    lower = sorted_keys[0]
    upper = sorted_keys[-1]
    for k in sorted_keys:
        if k <= target:
            lower = k
        else:
            upper = k
            break

    # Exact hit on a sampled key - no interpolation needed.
    if lower == target:
        return lower, lower, 0.0

    if lower == upper:
        return lower, upper, 0.0

    t = (target - lower) / (upper - lower)
    return lower, upper, t


# ---------------------------------------------------------------------------
# 2-D bilinear interpolation  (color_temp: bri × mired)
# ---------------------------------------------------------------------------

# Type alias imported from color_temp - defined here to avoid circular import.
ColorTempLut = dict[int, dict[int, float]]


def interpolate_2d_bilinear(
    lut: ColorTempLut,
    brightness: int,
    color_temp: int,
) -> float:
    """Bilinear interpolation over a ``{bri: {mired: watt}}`` LUT.

    DEVIATION FROM ORIGINAL: the original implementation uses nearest-neighbour
    for the mired axis.  This function performs full bilinear interpolation:

    1. Locate the bri bracket [b0, b1] and fraction t_b.
    2. At b0: locate the mired bracket [m0, m1] and fraction t_m0;
       interpolate → w_b0.
    3. At b1: locate the mired bracket [m0, m1] and fraction t_m1;
       interpolate → w_b1.
    4. Interpolate w_b0 and w_b1 by t_b → result.

    Each brightness level uses its own mired bracket, so the interpolation is
    correct even for sparse / irregular LUTs where different bri levels contain
    different mired samples.

    Falls back to nearest-neighbour on the mired axis when a brightness level
    has only a single mired sample.
    """
    if not lut:
        return 0.0

    sorted_bri = sorted(lut)
    b0, b1, t_b = _find_bracket(sorted_bri, brightness)

    def _watt_at_bri(bri_key: int) -> float:
        mired_map = lut[bri_key]
        sorted_mired = sorted(mired_map)
        if len(sorted_mired) < 2:
            # Only one mired sample - nearest-neighbour fallback.
            best = nearest_key(sorted_mired, color_temp)
            return mired_map[best]
        m0, m1, t_m = _find_bracket(sorted_mired, color_temp)
        return lerp(mired_map[m0], mired_map[m1], t_m)

    w_b0 = _watt_at_bri(b0)
    w_b1 = _watt_at_bri(b1)
    return lerp(w_b0, w_b1, t_b)


# ---------------------------------------------------------------------------
# 3-D trilinear interpolation  (hs: bri × hue × sat)
# ---------------------------------------------------------------------------

HsLut = dict[int, dict[int, dict[int, float]]]


def interpolate_3d_trilinear(
    lut: HsLut,
    brightness: int,
    hue: int,
    saturation: int,
) -> float:
    """Trilinear interpolation over a ``{bri: {hue: {sat: watt}}}`` LUT.

    DEVIATION FROM ORIGINAL: the original implementation uses nearest-neighbour
    for both the hue and saturation axes.  This function performs full
    trilinear interpolation across all three axes:

    1. Locate the bri bracket [b0, b1] and fraction t_b.
    2. At each bri level:
       a. Locate the hue bracket [h0, h1] and fraction t_h.
       b. At each hue level: locate the sat bracket [s0, s1] and
          fraction t_s; interpolate → watt at (bri, hue).
       c. Interpolate the two hue results by t_h → watt at bri.
    3. Interpolate the two bri results by t_b → final watt.

    Falls back to nearest-neighbour on an axis when fewer than two distinct
    sample points are available for that axis at the current bracket position.
    """
    if not lut:
        return 0.0

    sorted_bri = sorted(lut)
    b0, b1, t_b = _find_bracket(sorted_bri, brightness)

    def _watt_at_bri_hue(bri_key: int, hue_key: int) -> float:
        sat_map = lut[bri_key][hue_key]
        sorted_sats = sorted(sat_map)
        if len(sorted_sats) < 2:
            best = nearest_key(sorted_sats, saturation)
            return sat_map[best]
        s0, s1, t_s = _find_bracket(sorted_sats, saturation)
        return lerp(sat_map[s0], sat_map[s1], t_s)

    def _watt_at_bri(bri_key: int) -> float:
        hue_map = lut[bri_key]
        sorted_hues = sorted(hue_map)
        if len(sorted_hues) < 2:
            best_hue = nearest_key(sorted_hues, hue)
            return _watt_at_bri_hue(bri_key, best_hue)
        h0, h1, t_h = _find_bracket(sorted_hues, hue)
        w_h0 = _watt_at_bri_hue(bri_key, h0)
        w_h1 = _watt_at_bri_hue(bri_key, h1)
        return lerp(w_h0, w_h1, t_h)

    w_b0 = _watt_at_bri(b0)
    w_b1 = _watt_at_bri(b1)
    return lerp(w_b0, w_b1, t_b)
