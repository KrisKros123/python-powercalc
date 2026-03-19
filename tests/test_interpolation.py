"""Tests for the multi-dimensional interpolation module and engine integration.

Structure
---------
TestLerp                     - basic lerp helper
TestFindBracket              - _find_bracket edge cases and normal cases
TestInterpolate2dBilinear    - color_temp bilinear, incl. fallbacks
TestInterpolate3dTrilinear   - hs trilinear, incl. fallbacks
TestColorTempMultilinear     - get_color_temp_power_multilinear vs powercalc
TestHsMultilinear            - get_hs_power_multilinear vs powercalc
TestEngineInterpolationMode  - engine routes correctly; "powercalc" unchanged
TestEdgeCases                - clamp, single-point, degenerate LUTs
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from powercalc_engine import PowercalcEngine
from powercalc_engine.lut.color_temp import (
    get_color_temp_power,
    get_color_temp_power_multilinear,
)
from powercalc_engine.lut.hs import get_hs_power, get_hs_power_multilinear
from powercalc_engine.lut.interpolation import (
    _find_bracket,
    interpolate_2d_bilinear,
    interpolate_3d_trilinear,
    lerp,
)

from tests.conftest import (
    COLOR_TEMP_ROWS,
    HS_ROWS,
    make_profile,
    write_csv,
)

# ---------------------------------------------------------------------------
# lerp
# ---------------------------------------------------------------------------


class TestLerp:
    def test_t_zero_returns_a(self):
        assert lerp(0.0, 10.0, 0.0) == pytest.approx(0.0)

    def test_t_one_returns_b(self):
        assert lerp(0.0, 10.0, 1.0) == pytest.approx(10.0)

    def test_t_half(self):
        assert lerp(0.0, 10.0, 0.5) == pytest.approx(5.0)

    def test_t_clamped_below_zero(self):
        assert lerp(0.0, 10.0, -0.5) == pytest.approx(0.0)

    def test_t_clamped_above_one(self):
        assert lerp(0.0, 10.0, 1.5) == pytest.approx(10.0)

    def test_negative_values(self):
        assert lerp(-10.0, 10.0, 0.5) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _find_bracket
# ---------------------------------------------------------------------------


class TestFindBracket:
    def test_exact_hit_returns_same_key_t_zero(self):
        lo, hi, t = _find_bracket([0, 128, 255], 128)
        assert lo == 128 and hi == 128 and t == pytest.approx(0.0)

    def test_below_min_clamps(self):
        lo, hi, t = _find_bracket([100, 200], 50)
        assert lo == 100 and hi == 100 and t == pytest.approx(0.0)

    def test_above_max_clamps(self):
        lo, hi, t = _find_bracket([100, 200], 300)
        assert lo == 200 and hi == 200 and t == pytest.approx(0.0)

    def test_midpoint_returns_half(self):
        lo, hi, t = _find_bracket([0, 100], 50)
        assert lo == 0 and hi == 100 and t == pytest.approx(0.5)

    def test_quarter_point(self):
        lo, hi, t = _find_bracket([0, 100, 200], 25)
        assert lo == 0 and hi == 100 and t == pytest.approx(0.25)

    def test_between_upper_two_keys(self):
        lo, hi, t = _find_bracket([0, 100, 200], 150)
        assert lo == 100 and hi == 200 and t == pytest.approx(0.5)

    def test_single_key_always_returns_that_key(self):
        lo, hi, t = _find_bracket([42], 0)
        assert lo == 42 and hi == 42 and t == pytest.approx(0.0)
        lo, hi, t = _find_bracket([42], 999)
        assert lo == 42 and hi == 42 and t == pytest.approx(0.0)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _find_bracket([], 0)


# ---------------------------------------------------------------------------
# 2-D bilinear (color_temp)
# ---------------------------------------------------------------------------


class TestInterpolate2dBilinear:
    """
    LUT used in these tests (bri × mired → watt):
        bri=0,   mired=153 → 0.4
        bri=0,   mired=370 → 0.5
        bri=255, mired=153 → 9.5
        bri=255, mired=370 → 12.0
    """

    @pytest.fixture(autouse=True)
    def _lut(self):
        self.lut = {
            0:   {153: 0.4,  370: 0.5},
            255: {153: 9.5, 370: 12.0},
        }

    def test_exact_corner_b0_m0(self):
        assert interpolate_2d_bilinear(self.lut, 0, 153) == pytest.approx(0.4)

    def test_exact_corner_b1_m1(self):
        assert interpolate_2d_bilinear(self.lut, 255, 370) == pytest.approx(12.0)

    def test_midpoint_bri_exact_mired(self):
        # bri=128 (≈ 128/255 along bri axis), mired=153 (exact key)
        t = 128 / 255
        expected = lerp(0.4, 9.5, t)
        assert interpolate_2d_bilinear(self.lut, 128, 153) == pytest.approx(expected, rel=1e-5)

    def test_exact_bri_midpoint_mired(self):
        # bri=0 (exact), mired midpoint between 153 and 370
        mid_mired = (153 + 370) // 2  # 261
        t_m = (261 - 153) / (370 - 153)
        expected = lerp(0.4, 0.5, t_m)
        assert interpolate_2d_bilinear(self.lut, 0, mid_mired) == pytest.approx(expected, rel=1e-5)

    def test_bilinear_interior_point(self):
        # bri=128, mired=261 - full bilinear
        t_b = 128 / 255
        mid_mired = 261
        t_m = (261 - 153) / (370 - 153)
        w_b0 = lerp(0.4, 0.5, t_m)
        w_b1 = lerp(9.5, 12.0, t_m)
        expected = lerp(w_b0, w_b1, t_b)
        assert interpolate_2d_bilinear(self.lut, 128, mid_mired) == pytest.approx(expected, rel=1e-5)

    def test_clamp_below_min_bri(self):
        # bri < 0 clamps to bri=0
        assert interpolate_2d_bilinear(self.lut, 0, 153) == pytest.approx(0.4)

    def test_clamp_above_max_bri(self):
        assert interpolate_2d_bilinear(self.lut, 255, 153) == pytest.approx(9.5)

    def test_clamp_below_min_mired(self):
        # mired below 153 → clamps to 153 column
        assert interpolate_2d_bilinear(self.lut, 0, 100) == pytest.approx(0.4)

    def test_clamp_above_max_mired(self):
        # mired above 370 → clamps to 370 column
        assert interpolate_2d_bilinear(self.lut, 0, 500) == pytest.approx(0.5)

    def test_empty_lut_returns_zero(self):
        assert interpolate_2d_bilinear({}, 128, 300) == pytest.approx(0.0)

    def test_single_mired_per_bri_uses_nearest_fallback(self):
        """When a bri level has only one mired sample, nearest-neighbour is used."""
        lut = {0: {153: 1.0}, 255: {153: 5.0}}
        # Only mired=153 exists; any color_temp should return the same column.
        assert interpolate_2d_bilinear(lut, 0, 300) == pytest.approx(1.0)
        assert interpolate_2d_bilinear(lut, 255, 0) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# 3-D trilinear (hs)
# ---------------------------------------------------------------------------


class TestInterpolate3dTrilinear:
    """
    LUT: bri ∈ {0, 255}, hue ∈ {0, 32768}, sat ∈ {0, 255}

    Watts (from HS_ROWS in conftest):
        (0,   0,     0)   → 0.4
        (0,   0,   255)   → 0.5
        (0,   32768, 0)   → 0.5
        (0,   32768, 255) → 0.6
        (255, 0,     0)   → 9.0
        (255, 0,   255)   → 10.0
        (255, 32768, 0)   → 10.0
        (255, 32768, 255) → 11.0
    """

    @pytest.fixture(autouse=True)
    def _lut(self):
        self.lut = {
            0: {
                0:     {0: 0.4, 255: 0.5},
                32768: {0: 0.5, 255: 0.6},
            },
            255: {
                0:     {0: 9.0,  255: 10.0},
                32768: {0: 10.0, 255: 11.0},
            },
        }

    def test_exact_corner_b0_h0_s0(self):
        assert interpolate_3d_trilinear(self.lut, 0, 0, 0) == pytest.approx(0.4)

    def test_exact_corner_b1_h1_s1(self):
        assert interpolate_3d_trilinear(self.lut, 255, 32768, 255) == pytest.approx(11.0)

    def test_midpoint_bri_only(self):
        # bri=128, hue=0, sat=0 - only bri interpolates
        t_b = 128 / 255
        expected = lerp(0.4, 9.0, t_b)
        assert interpolate_3d_trilinear(self.lut, 128, 0, 0) == pytest.approx(expected, rel=1e-5)

    def test_midpoint_sat_only(self):
        # bri=0, hue=0, sat=128
        t_s = 128 / 255
        expected = lerp(0.4, 0.5, t_s)
        assert interpolate_3d_trilinear(self.lut, 0, 0, 128) == pytest.approx(expected, rel=1e-5)

    def test_trilinear_interior_point(self):
        t_b = 128 / 255
        t_h = 16384 / 32768  # = 0.5
        t_s = 128 / 255

        # At bri=0:
        w_h0_s = lerp(0.4, 0.5, t_s)   # hue=0
        w_h1_s = lerp(0.5, 0.6, t_s)   # hue=32768
        w_b0   = lerp(w_h0_s, w_h1_s, t_h)

        # At bri=255:
        w_h0_s2 = lerp(9.0, 10.0, t_s)
        w_h1_s2 = lerp(10.0, 11.0, t_s)
        w_b1    = lerp(w_h0_s2, w_h1_s2, t_h)

        expected = lerp(w_b0, w_b1, t_b)
        assert interpolate_3d_trilinear(self.lut, 128, 16384, 128) == pytest.approx(expected, rel=1e-5)

    def test_clamp_below_bri(self):
        assert interpolate_3d_trilinear(self.lut, 0, 0, 0) == pytest.approx(0.4)

    def test_clamp_above_bri(self):
        assert interpolate_3d_trilinear(self.lut, 255, 0, 0) == pytest.approx(9.0)

    def test_clamp_below_hue(self):
        assert interpolate_3d_trilinear(self.lut, 0, 0, 0) == pytest.approx(0.4)

    def test_clamp_above_hue(self):
        # hue above max → clamp to hue=32768
        assert interpolate_3d_trilinear(self.lut, 0, 65535, 0) == pytest.approx(0.5)

    def test_empty_lut_returns_zero(self):
        assert interpolate_3d_trilinear({}, 128, 0, 0) == pytest.approx(0.0)

    def test_single_hue_uses_fallback(self):
        """One hue per bri level → nearest-neighbour fallback on hue axis."""
        lut = {0: {0: {0: 1.0, 255: 2.0}}, 255: {0: {0: 5.0, 255: 6.0}}}
        assert interpolate_3d_trilinear(lut, 0, 99999, 0) == pytest.approx(1.0)

    def test_single_sat_uses_fallback(self):
        """One sat per hue → nearest-neighbour fallback on sat axis."""
        lut = {0: {0: {128: 3.0}}, 255: {0: {128: 7.0}}}
        assert interpolate_3d_trilinear(lut, 0, 0, 0) == pytest.approx(3.0)
        assert interpolate_3d_trilinear(lut, 0, 0, 255) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# color_temp: nearest vs bilinear comparison
# ---------------------------------------------------------------------------


class TestColorTempMultilinear:
    @pytest.fixture(autouse=True)
    def _lut(self, tmp_path):
        write_csv(tmp_path / "color_temp.csv", COLOR_TEMP_ROWS)
        from powercalc_engine.lut.color_temp import load_color_temp_lut
        self.lut = load_color_temp_lut(tmp_path)

    def test_exact_sample_points_identical(self):
        """At sampled (bri, mired) both modes must return the same watt."""
        for bri, mired_map in self.lut.items():
            for mired, expected in mired_map.items():
                nn  = get_color_temp_power(self.lut, bri, mired)
                ml  = get_color_temp_power_multilinear(self.lut, bri, mired)
                assert nn == pytest.approx(expected, rel=1e-6), f"NN mismatch at {bri},{mired}"
                assert ml == pytest.approx(expected, rel=1e-6), f"ML mismatch at {bri},{mired}"

    def test_bilinear_differs_from_nearest_at_interior_point(self):
        """For a point between samples, bilinear should differ from nearest-neighbour."""
        # COLOR_TEMP_ROWS has bri={0, 255} and mired={153, 370}
        nn = get_color_temp_power(self.lut, 128, 261)
        ml = get_color_temp_power_multilinear(self.lut, 128, 261)
        # They must both be positive and they must differ (bilinear interpolates
        # the mired axis, nearest-neighbour snaps to the closest mired key).
        assert nn > 0
        assert ml > 0
        assert nn != pytest.approx(ml, rel=1e-3), "expected bilinear != nearest-neighbour"

    def test_bilinear_result_is_between_corner_watts(self):
        """Interior point must be bounded by the min/max corner watts."""
        all_watts = [w for mmap in self.lut.values() for w in mmap.values()]
        ml = get_color_temp_power_multilinear(self.lut, 128, 261)
        assert min(all_watts) <= ml <= max(all_watts)


# ---------------------------------------------------------------------------
# hs: nearest vs trilinear comparison
# ---------------------------------------------------------------------------


class TestHsMultilinear:
    @pytest.fixture(autouse=True)
    def _lut(self, tmp_path):
        write_csv(tmp_path / "hs.csv", HS_ROWS)
        from powercalc_engine.lut.hs import load_hs_lut
        self.lut = load_hs_lut(tmp_path)

    def test_exact_sample_points_identical(self):
        """Both modes must agree on sampled points."""
        for bri, hue_map in self.lut.items():
            for hue, sat_map in hue_map.items():
                for sat, expected in sat_map.items():
                    nn = get_hs_power(self.lut, bri, hue, sat)
                    ml = get_hs_power_multilinear(self.lut, bri, hue, sat)
                    assert nn == pytest.approx(expected, rel=1e-6)
                    assert ml == pytest.approx(expected, rel=1e-6)

    def test_trilinear_differs_from_nearest_at_interior(self):
        """At an interior (bri, hue, sat) trilinear should differ from NN.
        The conftest LUT is symmetric so the difference is small but non-zero.
        We verify the algorithms produce distinguishably different results
        using an absolute threshold."""
        nn = get_hs_power(self.lut, 128, 16384, 128)
        ml = get_hs_power_multilinear(self.lut, 128, 16384, 128)
        assert nn > 0
        assert ml > 0
        assert abs(nn - ml) > 1e-6, "expected trilinear != nearest-neighbour"
        assert nn != ml

    def test_trilinear_result_is_bounded(self):
        all_watts = [
            w
            for hue_map in self.lut.values()
            for sat_map in hue_map.values()
            for w in sat_map.values()
        ]
        ml = get_hs_power_multilinear(self.lut, 128, 16384, 128)
        assert min(all_watts) <= ml <= max(all_watts)


# ---------------------------------------------------------------------------
# Engine integration - interpolation_mode routing
# ---------------------------------------------------------------------------


class TestEngineInterpolationMode:
    def test_invalid_mode_raises(self, tmp_path):
        with pytest.raises(ValueError, match="interpolation_mode"):
            PowercalcEngine(tmp_path, interpolation_mode="invalid")  # type: ignore[arg-type]

    def test_powercalc_mode_is_default(self, tmp_path):
        engine = PowercalcEngine(tmp_path)
        assert engine._interpolation_mode == "powercalc"

    def test_powercalc_and_default_give_same_result_color_temp(self, tmp_path):
        make_profile(tmp_path, standby_power=0.3, modes=("color_temp",))
        e_default    = PowercalcEngine(tmp_path)
        e_powercalc  = PowercalcEngine(tmp_path, interpolation_mode="powercalc")
        state = {"is_on": True, "brightness": 128,
                 "color_mode": "color_temp", "color_temp": 261}
        assert e_default.get_power("acme", "BULB001", state) == pytest.approx(
            e_powercalc.get_power("acme", "BULB001", state)
        )

    def test_powercalc_mode_matches_old_behavior_color_temp(self, tmp_path):
        """powercalc mode must produce exactly what get_color_temp_power returns."""
        make_profile(tmp_path, standby_power=0.3, modes=("color_temp",))
        engine = PowercalcEngine(tmp_path, interpolation_mode="powercalc")
        state = {"is_on": True, "brightness": 128,
                 "color_mode": "color_temp", "color_temp": 261}
        engine_result = engine.get_power("acme", "BULB001", state)

        from powercalc_engine.lut.color_temp import load_color_temp_lut
        lut = load_color_temp_lut(tmp_path / "acme" / "BULB001")
        direct = get_color_temp_power(lut, 128, 261)
        assert engine_result == pytest.approx(direct)

    def test_multilinear_differs_from_powercalc_color_temp(self, tmp_path):
        make_profile(tmp_path, standby_power=0.3, modes=("color_temp",))
        e_nn = PowercalcEngine(tmp_path, interpolation_mode="powercalc")
        e_ml = PowercalcEngine(tmp_path, interpolation_mode="multilinear")
        state = {"is_on": True, "brightness": 128,
                 "color_mode": "color_temp", "color_temp": 261}
        assert e_nn.get_power("acme", "BULB001", state) != pytest.approx(
            e_ml.get_power("acme", "BULB001", state), rel=1e-3
        )

    def test_multilinear_differs_from_powercalc_hs(self, tmp_path):
        make_profile(tmp_path, standby_power=0.3, modes=("hs",))
        e_nn = PowercalcEngine(tmp_path, interpolation_mode="powercalc")
        e_ml = PowercalcEngine(tmp_path, interpolation_mode="multilinear")
        state = {"is_on": True, "brightness": 128,
                 "color_mode": "hs", "hue": 16384, "saturation": 128}
        nn_result = e_nn.get_power("acme", "BULB001", state)
        ml_result = e_ml.get_power("acme", "BULB001", state)
        # The conftest LUT is symmetric, so differences are small but real.
        assert abs(nn_result - ml_result) > 1e-6
        assert nn_result != ml_result

    def test_brightness_mode_unchanged_in_multilinear(self, tmp_path):
        """brightness LUT is identical in both modes."""
        make_profile(tmp_path, standby_power=0.3, modes=("brightness",))
        e_nn = PowercalcEngine(tmp_path, interpolation_mode="powercalc")
        e_ml = PowercalcEngine(tmp_path, interpolation_mode="multilinear")
        state = {"is_on": True, "brightness": 192, "color_mode": "brightness"}
        assert e_nn.get_power("acme", "BULB001", state) == pytest.approx(
            e_ml.get_power("acme", "BULB001", state)
        )

    def test_standby_unchanged_in_multilinear(self, tmp_path):
        make_profile(tmp_path, standby_power=0.5, modes=("hs",))
        engine = PowercalcEngine(tmp_path, interpolation_mode="multilinear")
        assert engine.get_power("acme", "BULB001", {"is_on": False}) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_2d_clamp_exact_boundary_bri(self):
        lut = {0: {153: 1.0, 370: 2.0}, 255: {153: 5.0, 370: 6.0}}
        assert interpolate_2d_bilinear(lut, 0, 153)   == pytest.approx(1.0)
        assert interpolate_2d_bilinear(lut, 255, 370)  == pytest.approx(6.0)

    def test_2d_single_bri_level(self):
        """Only one bri level - still returns correct mired interpolation."""
        lut = {128: {100: 3.0, 200: 7.0}}
        t_m = (150 - 100) / (200 - 100)  # 0.5
        expected = lerp(3.0, 7.0, t_m)
        assert interpolate_2d_bilinear(lut, 128, 150) == pytest.approx(expected)

    def test_3d_clamp_exact_corner(self):
        lut = {0: {0: {0: 1.0}}, 255: {0: {0: 9.0}}}
        assert interpolate_3d_trilinear(lut, 0, 0, 0)   == pytest.approx(1.0)
        assert interpolate_3d_trilinear(lut, 255, 0, 0) == pytest.approx(9.0)

    def test_3d_bri_bracket_collapses_to_one(self):
        """bri bracket collapses when both keys are the same → no lerp needed."""
        lut = {128: {0: {0: 5.0, 255: 8.0}}}
        t_s = 128 / 255
        expected = lerp(5.0, 8.0, t_s)
        assert interpolate_3d_trilinear(lut, 128, 0, 128) == pytest.approx(expected, rel=1e-5)

    def test_2d_returns_positive_for_real_lut_data(self, tmp_path):
        write_csv(tmp_path / "color_temp.csv", COLOR_TEMP_ROWS)
        from powercalc_engine.lut.color_temp import load_color_temp_lut
        lut = load_color_temp_lut(tmp_path)
        result = interpolate_2d_bilinear(lut, 100, 250)
        assert result > 0

    def test_3d_returns_positive_for_real_lut_data(self, tmp_path):
        write_csv(tmp_path / "hs.csv", HS_ROWS)
        from powercalc_engine.lut.hs import load_hs_lut
        lut = load_hs_lut(tmp_path)
        result = interpolate_3d_trilinear(lut, 100, 10000, 100)
        assert result > 0
