"""Tests for shared interpolation helpers in lut/base.py."""

from __future__ import annotations

import pytest

from powercalc_engine.lut.base import interpolate_bri, nearest_key


class TestNearestKey:
    def test_exact_match(self):
        assert nearest_key([0, 128, 255], 128) == 128

    def test_left_neighbor_wins_on_tie(self):
        # Between 100 and 200 with target=150 - equidistant; lower wins.
        assert nearest_key([100, 200], 150) == 100

    def test_selects_lower_when_closer(self):
        assert nearest_key([0, 128, 255], 50) == 0  # closer to 0 than 128

    def test_selects_upper_when_closer(self):
        assert nearest_key([0, 128, 255], 200) == 255  # closer to 255 than 128

    def test_clamps_below(self):
        assert nearest_key([100, 200, 300], 50) == 100

    def test_clamps_above(self):
        assert nearest_key([100, 200, 300], 350) == 300

    def test_single_key(self):
        assert nearest_key([42], 0) == 42
        assert nearest_key([42], 99) == 42

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            nearest_key([], 0)


class TestInterpolateBri:
    def test_exact_key(self):
        lut = {0: 0.0, 128: 9.0, 255: 18.0}
        assert interpolate_bri(lut, 128) == pytest.approx(9.0)

    def test_interpolation_between_points(self):
        lut = {0: 0.0, 100: 10.0}
        # At bri=50: ratio=0.5 → watt=5.0
        assert interpolate_bri(lut, 50) == pytest.approx(5.0)

    def test_clamp_below_minimum(self):
        lut = {50: 2.0, 200: 8.0}
        assert interpolate_bri(lut, 0) == pytest.approx(2.0)

    def test_clamp_above_maximum(self):
        lut = {50: 2.0, 200: 8.0}
        assert interpolate_bri(lut, 255) == pytest.approx(8.0)

    def test_single_entry_always_returns_that_watt(self):
        lut = {128: 5.0}
        assert interpolate_bri(lut, 0) == pytest.approx(5.0)
        assert interpolate_bri(lut, 128) == pytest.approx(5.0)
        assert interpolate_bri(lut, 255) == pytest.approx(5.0)

    def test_empty_lut_returns_zero(self):
        assert interpolate_bri({}, 128) == pytest.approx(0.0)

    def test_non_uniform_step_interpolation(self):
        # 3-point LUT: 0→0W, 100→5W, 255→20W
        lut = {0: 0.0, 100: 5.0, 255: 20.0}
        # bri=50 between 0 and 100: ratio=0.5 → 2.5W
        assert interpolate_bri(lut, 50) == pytest.approx(2.5)
        # bri=177 between 100 and 255: ratio=(177-100)/155=77/155
        ratio = 77 / 155
        expected = 5.0 + ratio * (20.0 - 5.0)
        assert interpolate_bri(lut, 177) == pytest.approx(expected, rel=1e-6)
