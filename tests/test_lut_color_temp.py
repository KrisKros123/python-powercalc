"""Tests for the color_temp LUT module and engine integration."""

from __future__ import annotations

import pytest

from powercalc_engine import MissingLookupTableError, PowercalcEngine
from powercalc_engine.lut.color_temp import get_color_temp_power, load_color_temp_lut

from tests.conftest import COLOR_TEMP_ROWS, make_profile, write_csv, write_csv_gz


class TestLoadColorTempLut:
    def test_loads_plain_csv(self, tmp_path):
        write_csv(tmp_path / "color_temp.csv", COLOR_TEMP_ROWS)
        lut = load_color_temp_lut(tmp_path)
        assert 0 in lut
        assert 255 in lut
        assert lut[0][153] == pytest.approx(0.4)
        assert lut[255][370] == pytest.approx(12.0)

    def test_loads_gz(self, tmp_path):
        write_csv_gz(tmp_path / "color_temp.csv.gz", COLOR_TEMP_ROWS)
        lut = load_color_temp_lut(tmp_path)
        assert lut[255][153] == pytest.approx(9.5)

    def test_missing_raises(self, tmp_path):
        with pytest.raises(MissingLookupTableError):
            load_color_temp_lut(tmp_path)


class TestGetColorTempPower:
    @pytest.fixture(autouse=True)
    def _lut(self, tmp_path):
        write_csv(tmp_path / "color_temp.csv", COLOR_TEMP_ROWS)
        self.lut = load_color_temp_lut(tmp_path)

    def test_exact_low_bri_low_mired(self):
        # bri=0, mired=153 → exact key
        assert get_color_temp_power(self.lut, 0, 153) == pytest.approx(0.4)

    def test_exact_high_bri_high_mired(self):
        assert get_color_temp_power(self.lut, 255, 370) == pytest.approx(12.0)

    def test_nearest_mired_selection(self):
        # bri=0 has mired keys 153 and 370.  mired=200 is nearer to 153.
        assert get_color_temp_power(self.lut, 0, 200) == pytest.approx(0.4)

    def test_bri_interpolation(self):
        # bri=128 is halfway between 0 and 255.
        # At mired=153: watt_lower=0.4 (bri=0), watt_upper=9.5 (bri=255).
        ratio = 128 / 255
        expected = 0.4 + ratio * (9.5 - 0.4)
        assert get_color_temp_power(self.lut, 128, 153) == pytest.approx(expected, rel=1e-4)

    def test_clamp_below_min_bri(self):
        # bri=0 is the minimum sample; exact match expected.
        assert get_color_temp_power(self.lut, 0, 370) == pytest.approx(0.5)

    def test_clamp_above_max_bri(self):
        assert get_color_temp_power(self.lut, 255, 153) == pytest.approx(9.5)


class TestColorTempEngineIntegration:
    def test_engine_color_temp_mode(self, tmp_path):
        make_profile(tmp_path, standby_power=0.3, modes=("color_temp",))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={
                "is_on": True,
                "brightness": 255,
                "color_mode": "color_temp",
                "color_temp": 153,
            },
        )
        assert watts == pytest.approx(9.5)

    def test_standby_overrides_color_temp(self, tmp_path):
        make_profile(tmp_path, standby_power=0.4, modes=("color_temp",))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": False, "brightness": 255, "color_mode": "color_temp", "color_temp": 153},
        )
        assert watts == pytest.approx(0.4)
