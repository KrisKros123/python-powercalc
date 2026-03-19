"""Tests for _is_standby_state().

The function has exactly 4 rules - tests cover every branch and edge case,
and explicitly verify that the removed hs-specific branch is NOT needed
(those cases are already covered by rules 3 and 4).
"""

from __future__ import annotations

import pytest

from powercalc_engine.engine import _is_standby_state


class TestIsStandbyState:
    # Rule 1 - is_on == False
    def test_is_on_false_is_standby(self):
        assert _is_standby_state({"is_on": False}) is True

    def test_is_on_false_ignores_brightness(self):
        assert _is_standby_state({"is_on": False, "brightness": 255}) is True

    def test_is_on_false_ignores_active_effect(self):
        assert _is_standby_state({"is_on": False, "brightness": 200, "effect": "candle"}) is True

    # Rule 2 - active effect → NOT standby
    def test_active_effect_not_standby(self):
        assert _is_standby_state({"is_on": True, "brightness": 100, "effect": "candle"}) is False

    def test_active_effect_with_zero_brightness_not_standby(self):
        # brightness=0 but effect is active → the device is doing something.
        assert _is_standby_state({"is_on": True, "brightness": 0, "effect": "fireplace"}) is False

    def test_active_effect_with_none_brightness_not_standby(self):
        assert _is_standby_state({"is_on": True, "brightness": None, "effect": "candle"}) is False

    # Rule 3 - brightness == 0
    def test_brightness_zero_is_standby(self):
        assert _is_standby_state({"is_on": True, "brightness": 0}) is True

    def test_brightness_zero_hs_mode_is_standby(self):
        # hue/sat values don't matter when brightness is 0 - rule 3 fires.
        assert _is_standby_state({
            "is_on": True, "brightness": 0,
            "color_mode": "hs", "hue": 32000, "saturation": 200,
        }) is True

    def test_brightness_zero_color_temp_mode_is_standby(self):
        assert _is_standby_state({
            "is_on": True, "brightness": 0,
            "color_mode": "color_temp", "color_temp": 300,
        }) is True

    # Rule 4 - brightness is None
    def test_brightness_none_is_standby(self):
        assert _is_standby_state({"is_on": True, "brightness": None}) is True

    def test_brightness_absent_is_standby(self):
        # Key not present at all → same as None via .get() default.
        assert _is_standby_state({"is_on": True}) is True

    def test_brightness_none_hs_with_zeroed_hue_sat_is_standby(self):
        # Still standby - covered by rule 4, NOT by any hs-specific logic.
        assert _is_standby_state({
            "is_on": True, "brightness": None,
            "color_mode": "hs", "hue": 0, "saturation": 0,
        }) is True

    def test_brightness_none_hs_with_nonzero_hue_is_standby(self):
        # hue != 0 doesn't rescue it - rule 4 fires regardless.
        assert _is_standby_state({
            "is_on": True, "brightness": None,
            "color_mode": "hs", "hue": 1000, "saturation": 0,
        }) is True

    # Rule 5 - everything else is NOT standby
    def test_on_with_positive_brightness_not_standby(self):
        assert _is_standby_state({"is_on": True, "brightness": 128}) is False

    def test_on_brightness_1_not_standby(self):
        assert _is_standby_state({"is_on": True, "brightness": 1}) is False

    def test_on_brightness_255_not_standby(self):
        assert _is_standby_state({"is_on": True, "brightness": 255}) is False

    def test_default_is_on_true(self):
        # is_on absent → default True → not standby when brightness present.
        assert _is_standby_state({"brightness": 200}) is False
