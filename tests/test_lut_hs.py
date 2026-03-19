"""Tests for the hs (hue/saturation) LUT module and engine integration."""

from __future__ import annotations

import pytest

from powercalc_engine import MissingLookupTableError, PowercalcEngine
from powercalc_engine.lut.hs import get_hs_power, load_hs_lut

from tests.conftest import HS_ROWS, make_profile, write_csv, write_csv_gz


class TestLoadHsLut:
    def test_loads_plain_csv(self, tmp_path):
        write_csv(tmp_path / "hs.csv", HS_ROWS)
        lut = load_hs_lut(tmp_path)
        assert 0 in lut
        assert 255 in lut
        assert lut[0][0][0] == pytest.approx(0.4)

    def test_loads_gz(self, tmp_path):
        write_csv_gz(tmp_path / "hs.csv.gz", HS_ROWS)
        lut = load_hs_lut(tmp_path)
        assert lut[255][32768][255] == pytest.approx(11.0)

    def test_missing_raises(self, tmp_path):
        with pytest.raises(MissingLookupTableError):
            load_hs_lut(tmp_path)


class TestGetHsPower:
    """
    HS_ROWS has brightness levels 0 and 255.
    Hue levels per brightness: 0, 32768.
    Saturation levels per hue: 0, 255.

    Watts at bri=0:
        hue=0,     sat=0   → 0.4
        hue=0,     sat=255 → 0.5
        hue=32768, sat=0   → 0.5
        hue=32768, sat=255 → 0.6

    Watts at bri=255:
        hue=0,     sat=0   → 9.0
        hue=0,     sat=255 → 10.0
        hue=32768, sat=0   → 10.0
        hue=32768, sat=255 → 11.0
    """

    @pytest.fixture(autouse=True)
    def _lut(self, tmp_path):
        write_csv(tmp_path / "hs.csv", HS_ROWS)
        self.lut = load_hs_lut(tmp_path)

    def test_exact_bri0_hue0_sat0(self):
        assert get_hs_power(self.lut, 0, 0, 0) == pytest.approx(0.4)

    def test_exact_bri255_hue32768_sat255(self):
        assert get_hs_power(self.lut, 255, 32768, 255) == pytest.approx(11.0)

    def test_nearest_hue_selection(self):
        # hue=10000 is closer to 0 than to 32768 → uses hue=0 row.
        # bri=0, sat=0 → watt=0.4
        assert get_hs_power(self.lut, 0, 10000, 0) == pytest.approx(0.4)

    def test_nearest_sat_selection(self):
        # sat=200 is closer to 255 than to 0.
        # bri=255, hue=0, sat→255 → 10.0
        assert get_hs_power(self.lut, 255, 0, 200) == pytest.approx(10.0)

    def test_bri_interpolation_midpoint(self):
        # bri=128 halfway between 0 and 255.
        # hue=0, sat=0: watt_lower=0.4, watt_upper=9.0
        ratio = 128 / 255
        expected = 0.4 + ratio * (9.0 - 0.4)
        assert get_hs_power(self.lut, 128, 0, 0) == pytest.approx(expected, rel=1e-4)

    def test_clamp_below_min_bri(self):
        # bri=0 is the floor → watt at bri=0.
        assert get_hs_power(self.lut, 0, 0, 0) == pytest.approx(0.4)

    def test_clamp_above_max_bri(self):
        assert get_hs_power(self.lut, 255, 0, 0) == pytest.approx(9.0)


class TestHsEngineIntegration:
    def test_engine_hs_mode(self, tmp_path):
        make_profile(tmp_path, standby_power=0.3, modes=("hs",))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={
                "is_on": True,
                "brightness": 255,
                "color_mode": "hs",
                "hue": 0,
                "saturation": 0,
            },
        )
        assert watts == pytest.approx(9.0)

    def test_engine_hs_standby_on_off(self, tmp_path):
        make_profile(tmp_path, standby_power=0.7, modes=("hs",))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": False, "brightness": 255, "color_mode": "hs",
                   "hue": 32768, "saturation": 255},
        )
        assert watts == pytest.approx(0.7)

    def test_engine_hs_brightness_zero_returns_standby(self, tmp_path):
        make_profile(tmp_path, standby_power=0.7, modes=("hs",))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": True, "brightness": 0, "color_mode": "hs",
                   "hue": 32768, "saturation": 255},
        )
        assert watts == pytest.approx(0.7)
