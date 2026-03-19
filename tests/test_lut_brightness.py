"""Tests for the brightness LUT module and engine integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from powercalc_engine import MissingLookupTableError, PowercalcEngine
from powercalc_engine.lut.brightness import get_brightness_power, load_brightness_lut

from tests.conftest import BRIGHTNESS_ROWS, make_profile, write_csv, write_csv_gz


class TestLoadBrightnessLut:
    def test_loads_plain_csv(self, tmp_path):
        path = tmp_path
        write_csv(path / "brightness.csv", BRIGHTNESS_ROWS)
        lut = load_brightness_lut(path)
        assert lut[0] == pytest.approx(0.4)
        assert lut[128] == pytest.approx(9.0)
        assert lut[255] == pytest.approx(18.0)

    def test_loads_gz_csv(self, tmp_path):
        write_csv_gz(tmp_path / "brightness.csv.gz", BRIGHTNESS_ROWS)
        lut = load_brightness_lut(tmp_path)
        assert lut[255] == pytest.approx(18.0)

    def test_gz_preferred_over_plain(self, tmp_path):
        """When both exist, .csv.gz takes priority."""
        # Plain CSV with wrong watt value.
        write_csv(tmp_path / "brightness.csv", [["bri", "watt"], [255, 99.0]])
        # GZ with correct value.
        write_csv_gz(tmp_path / "brightness.csv.gz", BRIGHTNESS_ROWS)
        lut = load_brightness_lut(tmp_path)
        assert lut[255] == pytest.approx(18.0)  # from gz, not plain

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(MissingLookupTableError):
            load_brightness_lut(tmp_path)


class TestGetBrightnessPower:
    @pytest.fixture(autouse=True)
    def _lut(self, tmp_path):
        write_csv(tmp_path / "brightness.csv", BRIGHTNESS_ROWS)
        self.lut = load_brightness_lut(tmp_path)

    def test_exact_match_low(self):
        assert get_brightness_power(self.lut, 0) == pytest.approx(0.4)

    def test_exact_match_mid(self):
        assert get_brightness_power(self.lut, 128) == pytest.approx(9.0)

    def test_exact_match_high(self):
        assert get_brightness_power(self.lut, 255) == pytest.approx(18.0)

    def test_interpolation_midpoint(self):
        # Between bri=128 (9.0W) and bri=255 (18.0W) at bri=192 (halfway≈64).
        # ratio = (192-128)/(255-128) = 64/127 ≈ 0.5039
        expected = 9.0 + (18.0 - 9.0) * (64 / 127)
        assert get_brightness_power(self.lut, 192) == pytest.approx(expected, rel=1e-6)

    def test_clamp_below_minimum(self):
        # Any value <= 0 should return the 0 entry's watt.
        assert get_brightness_power(self.lut, 0) == pytest.approx(0.4)

    def test_clamp_above_maximum(self):
        assert get_brightness_power(self.lut, 255) == pytest.approx(18.0)


class TestBrightnessEngineIntegration:
    def test_engine_brightness_mode(self, tmp_path):
        make_profile(tmp_path, standby_power=0.3, modes=("brightness",))
        engine = PowercalcEngine(tmp_path)
        assert engine.get_power(
            "acme", "BULB001",
            state={"is_on": True, "brightness": 255, "color_mode": "brightness"},
        ) == pytest.approx(18.0)

    def test_engine_brightness_gz(self, gz_profile):
        lib, _ = gz_profile
        engine = PowercalcEngine(lib)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": True, "brightness": 255, "color_mode": "brightness"},
        )
        assert watts == pytest.approx(18.0)
