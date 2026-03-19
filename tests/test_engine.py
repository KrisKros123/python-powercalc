"""Tests for PowercalcEngine - standby/off logic and mode dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from powercalc_engine import (
    LutCalculationError,
    ModelNotFoundError,
    MissingLookupTableError,
    PowercalcEngine,
)

from tests.conftest import make_profile


# ---------------------------------------------------------------------------
# Standby / off tests
# ---------------------------------------------------------------------------


class TestStandby:
    def test_is_on_false_returns_standby(self, brightness_profile):
        lib, _ = brightness_profile
        engine = PowercalcEngine(lib)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": False, "brightness": 200, "color_mode": "brightness"},
        )
        assert watts == pytest.approx(0.3)

    def test_is_on_false_returns_zero_when_no_standby(self, tmp_path):
        """When model.json has no standby_power, off → 0.0."""
        make_profile(tmp_path, standby_power=None, modes=("brightness",))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": False, "brightness": 200, "color_mode": "brightness"},
        )
        assert watts == 0.0

    def test_brightness_zero_returns_standby(self, brightness_profile):
        lib, _ = brightness_profile
        engine = PowercalcEngine(lib)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": True, "brightness": 0, "color_mode": "brightness"},
        )
        assert watts == pytest.approx(0.3)

    def test_brightness_zero_returns_zero_when_no_standby(self, tmp_path):
        make_profile(tmp_path, standby_power=None, modes=("brightness",))
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": True, "brightness": 0, "color_mode": "brightness"},
        )
        assert watts == 0.0

    def test_brightness_none_returns_standby(self, brightness_profile):
        """brightness=None with no effect is treated as standby."""
        lib, _ = brightness_profile
        engine = PowercalcEngine(lib)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": True, "brightness": None, "color_mode": "brightness"},
        )
        assert watts == pytest.approx(0.3)

    def test_standby_power_float_string_in_json(self, tmp_path):
        """standby_power stored as a string in model.json must still work."""
        import json
        profile_path = tmp_path / "acme" / "BULB001"
        profile_path.mkdir(parents=True)
        (profile_path / "model.json").write_text(
            json.dumps({"standby_power": "0.25"}), encoding="utf-8"
        )
        from tests.conftest import write_csv, BRIGHTNESS_ROWS
        write_csv(profile_path / "brightness.csv", BRIGHTNESS_ROWS)
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": False},
        )
        assert watts == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Model lookup
# ---------------------------------------------------------------------------


class TestModelLookup:
    def test_missing_model_raises(self, tmp_path):
        engine = PowercalcEngine(tmp_path)
        with pytest.raises(ModelNotFoundError):
            engine.get_power("nonexistent", "MODEL", state={"is_on": True, "brightness": 100})

    def test_case_insensitive_manufacturer(self, tmp_path):
        make_profile(tmp_path, manufacturer="signify", model="LCA001",
                     standby_power=0.3, modes=("brightness",))
        engine = PowercalcEngine(tmp_path)
        # Uppercase manufacturer should still resolve.
        watts = engine.get_power(
            "SIGNIFY", "LCA001",
            state={"is_on": False},
        )
        assert watts == pytest.approx(0.3)

    def test_profile_is_cached(self, brightness_profile):
        lib, _ = brightness_profile
        engine = PowercalcEngine(lib)
        p1 = engine.get_profile("acme", "BULB001")
        p2 = engine.get_profile("acme", "BULB001")
        assert p1 is p2  # same object from cache


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------


class TestModeDispatch:
    def test_dispatches_to_brightness_when_color_mode_brightness(self, brightness_profile):
        lib, _ = brightness_profile
        engine = PowercalcEngine(lib)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": True, "brightness": 255, "color_mode": "brightness"},
        )
        assert watts == pytest.approx(18.0)

    def test_dispatches_to_brightness_as_fallback(self, brightness_profile):
        """No color_mode specified - should fall back to brightness LUT."""
        lib, _ = brightness_profile
        engine = PowercalcEngine(lib)
        watts = engine.get_power(
            "acme", "BULB001",
            state={"is_on": True, "brightness": 128},
        )
        assert watts == pytest.approx(9.0)

    def test_no_applicable_lut_raises(self, tmp_path):
        """Profile has no LUT files at all → MissingLookupTableError."""
        profile_dir = tmp_path / "acme" / "BULB001"
        profile_dir.mkdir(parents=True)
        import json
        (profile_dir / "model.json").write_text(json.dumps({}))
        engine = PowercalcEngine(tmp_path)
        with pytest.raises(MissingLookupTableError):
            engine.get_power(
                "acme", "BULB001",
                state={"is_on": True, "brightness": 100, "color_mode": "brightness"},
            )

    def test_lut_cached_across_calls(self, brightness_profile):
        """Second call does not re-read the CSV (lut cache hit)."""
        lib, _ = brightness_profile
        engine = PowercalcEngine(lib)
        engine.get_power("acme", "BULB001",
                         state={"is_on": True, "brightness": 128, "color_mode": "brightness"})
        # Verify cache entry exists.
        profile = engine.get_profile("acme", "BULB001")
        cache_key = (str(profile.path), "brightness")
        assert cache_key in engine._lut_cache
