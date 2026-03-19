"""Main engine - :class:`PowercalcEngine`.

Standby / off-like state detection
------------------------------------
A device is in standby whenever (evaluated in order, short-circuit):

  1. ``is_on == False``
  2. ``effect`` is set and non-empty → explicitly NOT standby; skip to LUT.
  3. ``brightness == 0``            → standby.
  4. ``brightness is None``         → standby.

DEVIATION FROM ORIGINAL: HA always provides brightness from the entity state.
Rules 3-4 exist only in the standalone library to handle callers that omit or
zero-out brightness.

Mode selection priority:  effect > hs > color_temp > brightness

Interpolation modes
-------------------
"powercalc"   (default) - original behaviour: linear on brightness, nearest-
              neighbour on all other axes (mired, hue, sat).
"multilinear" - DEVIATION FROM ORIGINAL: bilinear for color_temp (bri × mired),
              trilinear for hs (bri × hue × sat).  Falls back to nearest-
              neighbour per-axis when fewer than 2 sample points exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from .exceptions import LutCalculationError, MissingLookupTableError
from .loader import load_profile
from .lut.brightness import get_brightness_power, load_brightness_lut
from .lut.color_temp import (
    get_color_temp_power,
    get_color_temp_power_multilinear,
    load_color_temp_lut,
)
from .lut.effect import get_effect_power, load_effect_lut
from .lut.hs import get_hs_power, get_hs_power_multilinear, load_hs_lut
from .models import DeviceState, ModelProfile

InterpolationMode = Literal["powercalc", "multilinear"]
_VALID_MODES = frozenset({"powercalc", "multilinear"})


def _is_standby_state(state: DeviceState) -> bool:
    """Return True when *state* represents a standby / off-like condition."""
    if not state.get("is_on", True):
        return True
    if state.get("effect"):
        return False
    brightness: int | None = state.get("brightness")  # type: ignore[assignment]
    return brightness is None or brightness == 0


class PowercalcEngine:
    """Calculate device power draw from powercalc profile LUTs.

    Parameters
    ----------
    profile_dir        : Root of the profile library (``<mfr>/<model>/…``).
    interpolation_mode : ``"powercalc"`` (default - original nearest-neighbour
                         behaviour) or ``"multilinear"`` (bilinear for
                         color_temp, trilinear for hs).

    DEVIATION FROM ORIGINAL: ``interpolation_mode`` parameter is new.  The
    ``"powercalc"`` default preserves the original behaviour exactly.
    """

    def __init__(
        self,
        profile_dir: str | Path,
        interpolation_mode: InterpolationMode = "powercalc",
    ) -> None:
        if interpolation_mode not in _VALID_MODES:
            raise ValueError(
                f"interpolation_mode must be one of {sorted(_VALID_MODES)}, "
                f"got {interpolation_mode!r}"
            )
        self._profile_dir = Path(profile_dir)
        self._interpolation_mode: InterpolationMode = interpolation_mode
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
        """Return power draw in watts for *state*."""
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

        brightness: int = state.get("brightness")  # type: ignore[assignment]
        effect: str | None = state.get("effect")  # type: ignore[assignment]
        color_mode: str | None = state.get("color_mode")  # type: ignore[assignment]
        multilinear = self._interpolation_mode == "multilinear"

        # Effect mode (highest priority) - linear on bri only, no change.
        if effect and profile.has_mode("effect"):
            try:
                return get_effect_power(
                    self._get_effect_lut(profile), effect, brightness
                )
            except LutCalculationError:
                pass  # unknown effect → fall through

        # HS mode.
        if color_mode == "hs" and profile.has_mode("hs"):
            hue: int = state.get("hue") or 0  # type: ignore[assignment]
            sat: int = state.get("saturation") or 0  # type: ignore[assignment]
            lut_hs = self._get_hs_lut(profile)
            if multilinear:
                # DEVIATION FROM ORIGINAL: trilinear instead of nearest-neighbour.
                return get_hs_power_multilinear(lut_hs, brightness, hue, sat)
            return get_hs_power(lut_hs, brightness, hue, sat)

        # Color-temperature mode.
        if color_mode == "color_temp" and profile.has_mode("color_temp"):
            ct: int = state.get("color_temp") or 0  # type: ignore[assignment]
            lut_ct = self._get_color_temp_lut(profile)
            if multilinear:
                # DEVIATION FROM ORIGINAL: bilinear instead of nearest-neighbour.
                return get_color_temp_power_multilinear(lut_ct, brightness, ct)
            return get_color_temp_power(lut_ct, brightness, ct)

        # Brightness fallback - same in both modes.
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
