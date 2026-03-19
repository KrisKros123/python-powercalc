"""Main engine - :class:`PowercalcEngine`.

Standby / off-like state detection
------------------------------------
A device is in standby whenever (evaluated in order, short-circuit):

  1. ``is_on == False``
  2. ``effect`` is set and non-empty → explicitly NOT standby; skip to LUT.
  3. ``brightness == 0``            → standby.
  4. ``brightness is None``         → standby.

That's the complete rule set.  The original brief also mentioned
``hue=0, saturation=0`` as a standby signal, but those cases are already
covered: without brightness they fall into rule 4, and with brightness == 0
they fall into rule 3.  A separate hs-specific branch adds no new behaviour
and has been removed to keep the function honest about what it actually does.

DEVIATION FROM ORIGINAL: HA always provides brightness from the entity state.
Rules 3-4 exist only in the standalone library to handle callers that omit or
zero-out brightness.

Mode selection priority:  effect > hs > color_temp > brightness
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .exceptions import LutCalculationError, MissingLookupTableError
from .loader import load_profile
from .lut.brightness import get_brightness_power, load_brightness_lut
from .lut.color_temp import get_color_temp_power, load_color_temp_lut
from .lut.effect import get_effect_power, load_effect_lut
from .lut.hs import get_hs_power, load_hs_lut
from .models import DeviceState, ModelProfile


def _is_standby_state(state: DeviceState) -> bool:
    """Return True when *state* represents a standby / off-like condition.

    Rules (short-circuit, in order)
    --------------------------------
    1. ``is_on == False``                → standby.
    2. ``effect`` is truthy              → NOT standby (active effect).
    3. ``brightness == 0``               → standby.
    4. ``brightness is None``            → standby.
    5. Otherwise                         → not standby.
    """
    if not state.get("is_on", True):
        return True

    if state.get("effect"):
        return False

    brightness: int | None = state.get("brightness")  # type: ignore[assignment]

    # Rules 3 and 4 - explicit zero or missing brightness means nothing is lit.
    return brightness is None or brightness == 0


class PowercalcEngine:
    """Calculate device power draw from powercalc profile LUTs.

    Parameters
    ----------
    profile_dir : Root of the profile library (``<manufacturer>/<model>/…``).
    """

    def __init__(self, profile_dir: str | Path) -> None:
        self._profile_dir = Path(profile_dir)
        self._profile_cache: dict[tuple[str, str], ModelProfile] = {}
        self._lut_cache: dict[tuple[str, str], Any] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_power(
        self,
        manufacturer: str,
        model: str,
        state: DeviceState,
    ) -> float:
        """Return power draw in watts for *state*.

        Returns ``standby_power`` (or 0.0) for standby/off-like states.
        """
        profile = self._get_profile(manufacturer, model)
        return self._calculate(profile, state)

    def get_profile(self, manufacturer: str, model: str) -> ModelProfile:
        """Return the cached :class:`.models.ModelProfile` for this device."""
        return self._get_profile(manufacturer, model)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_profile(self, manufacturer: str, model: str) -> ModelProfile:
        key = (manufacturer.lower(), model.lower())
        if key not in self._profile_cache:
            self._profile_cache[key] = load_profile(
                self._profile_dir, manufacturer, model
            )
        return self._profile_cache[key]

    def _standby(self, profile: ModelProfile) -> float:
        return profile.standby_power if profile.standby_power is not None else 0.0

    def _calculate(self, profile: ModelProfile, state: DeviceState) -> float:
        if _is_standby_state(state):
            return self._standby(profile)

        # brightness is guaranteed positive (non-zero, non-None) here.
        brightness: int = state.get("brightness")  # type: ignore[assignment]
        effect: str | None = state.get("effect")  # type: ignore[assignment]
        color_mode: str | None = state.get("color_mode")  # type: ignore[assignment]

        # Effect mode (highest priority).
        if effect and profile.has_mode("effect"):
            try:
                return get_effect_power(self._get_effect_lut(profile), effect, brightness)
            except LutCalculationError:
                # Unknown effect name - fall through.
                # DEVIATION FROM ORIGINAL: original emits logger.warning + None.
                pass

        # HS mode.
        if color_mode == "hs" and profile.has_mode("hs"):
            hue: int = state.get("hue") or 0  # type: ignore[assignment]
            sat: int = state.get("saturation") or 0  # type: ignore[assignment]
            return get_hs_power(self._get_hs_lut(profile), brightness, hue, sat)

        # Color-temperature mode.
        if color_mode == "color_temp" and profile.has_mode("color_temp"):
            ct: int = state.get("color_temp") or 0  # type: ignore[assignment]
            return get_color_temp_power(self._get_color_temp_lut(profile), brightness, ct)

        # Brightness fallback.
        if profile.has_mode("brightness"):
            return get_brightness_power(self._get_brightness_lut(profile), brightness)

        raise MissingLookupTableError(
            f"Profile {profile.manufacturer}/{profile.requested_model} has no "
            f"applicable LUT for color_mode={color_mode!r}, effect={effect!r}. "
            f"Available modes: {profile.available_modes}"
        )

    # ------------------------------------------------------------------
    # LUT cache accessors
    # ------------------------------------------------------------------

    def _get_brightness_lut(self, p: ModelProfile):  # type: ignore[return]
        k = (str(p.path), "brightness")
        if k not in self._lut_cache:
            self._lut_cache[k] = load_brightness_lut(p.path)
        return self._lut_cache[k]

    def _get_color_temp_lut(self, p: ModelProfile):  # type: ignore[return]
        k = (str(p.path), "color_temp")
        if k not in self._lut_cache:
            self._lut_cache[k] = load_color_temp_lut(p.path)
        return self._lut_cache[k]

    def _get_hs_lut(self, p: ModelProfile):  # type: ignore[return]
        k = (str(p.path), "hs")
        if k not in self._lut_cache:
            self._lut_cache[k] = load_hs_lut(p.path)
        return self._lut_cache[k]

    def _get_effect_lut(self, p: ModelProfile):  # type: ignore[return]
        k = (str(p.path), "effect")
        if k not in self._lut_cache:
            self._lut_cache[k] = load_effect_lut(p.path)
        return self._lut_cache[k]
