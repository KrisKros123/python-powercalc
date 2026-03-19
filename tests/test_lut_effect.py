"""Tests for the effect LUT module and engine integration."""

from __future__ import annotations

import pytest

from powercalc_engine import LutCalculationError, MissingLookupTableError, PowercalcEngine
from powercalc_engine.lut.effect import get_effect_power, load_effect_lut

from tests.conftest import EFFECT_ROWS, make_profile, write_csv, write_csv_gz


class TestLoadEffectLut:
    def test_loads_plain_csv(self, tmp_path):
        write_csv(tmp_path / "effect.csv", EFFECT_ROWS)
        lut = load_effect_lut(tmp_path)
        assert "candle" in lut
        assert "fireplace" in lut
        assert lut["candle"][0] == pytest.approx(0.5)
        assert lut["candle"][255] == pytest.approx(8.0)

    def test_loads_gz(self, tmp_path):
        write_csv_gz(tmp_path / "effect.csv.gz", EFFECT_ROWS)
        lut = load_effect_lut(tmp_path)
        assert lut["fireplace"][255] == pytest.approx(9.0)

    def test_missing_raises(self, tmp_path):
        with pytest.raises(MissingLookupTableError):
            load_effect_lut(tmp_path)


class TestGetEffectPower:
    @pytest.fixture(autouse=True)
    def _lut(self, tmp_path):
        write_csv(tmp_path / "effect.csv", EFFECT_ROWS)
        self.lut = load_effect_lut(tmp_path)

    def test_exact_bri0(self):
        assert get_effect_power(self.lut, "candle", 0) == pytest.approx(0.5)

    def test_exact_bri255(self):
        assert get_effect_power(self.lut, "fireplace", 255) == pytest.approx(9.0)

    def test_interpolation_midpoint(self):
        # candle: bri=0→0.5W, bri=255→8.0W.  bri=128 ≈ halfway.
        ratio = 128 / 255
        expected = 0.5 + ratio * (8.0 - 0.5)
        assert get_effect_power(self.lut, "candle", 128) == pytest.approx(expected, rel=1e-4)

    def test_unknown_effect_raises(self):
        with pytest.raises(LutCalculationError, match="rainbow"):
            get_effect_power(self.lut, "rainbow", 128)


class TestEffectEngineIntegration:
    def test_engine_effect_mode_used_when_effect_active(self, tmp_path):
        make_profile(tmp_path, standby_power=0.3, modes=("effect", "brightness"))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={
                "is_on": True,
                "brightness": 255,
                "color_mode": "brightness",
                "effect": "candle",
            },
        )
        # effect mode should take priority over brightness mode
        assert watts == pytest.approx(8.0)

    def test_engine_unknown_effect_falls_through_to_brightness(self, tmp_path):
        """Unknown effect → fall through to next available mode (brightness)."""
        make_profile(tmp_path, standby_power=0.3, modes=("effect", "brightness"))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={
                "is_on": True,
                "brightness": 255,
                "color_mode": "brightness",
                "effect": "nonexistent_effect",
            },
        )
        # Falls through to brightness LUT → 18.0W
        assert watts == pytest.approx(18.0)

    def test_engine_effect_standby_when_off(self, tmp_path):
        make_profile(tmp_path, standby_power=0.6, modes=("effect", "brightness"))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": False, "brightness": 200, "effect": "candle"},
        )
        assert watts == pytest.approx(0.6)

    def test_engine_effect_active_overrides_bri_zero_standby(self, tmp_path):
        """brightness=0 BUT effect is active → should compute effect power, not standby."""
        make_profile(tmp_path, standby_power=0.3, modes=("effect", "brightness"))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": True, "brightness": 0, "effect": "candle"},
        )
        # effect.csv has bri=0 → 0.5W for candle
        assert watts == pytest.approx(0.5)
