"""Data models for powercalc_engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict


ColorMode = Literal["brightness", "color_temp", "hs", "effect"]


class DeviceState(TypedDict, total=False):
    is_on: bool
    brightness: int | None
    color_mode: ColorMode | None
    hue: int | None
    saturation: int | None
    color_temp: int | None
    effect: str | None


@dataclass
class ModelProfile:
    """Represents a loaded device profile from the profile library.

    Attributes
    ----------
    manufacturer     : Manufacturer directory name (e.g. "signify").
    requested_model  : The model name / alias as supplied by the caller.
                       May differ from canonical_model when an alias was used.
    canonical_model  : The actual directory name in the profile library.
                       Always reflects the on-disk directory regardless of
                       how the profile was looked up.
    path             : Absolute path used for LUT lookup.  Points to the
                       linked profile's directory when linked_profile is set.
    standby_power    : Power draw in standby/off state (from own model.json).
    available_modes  : LUT mode names for which a CSV/CSV.GZ file exists in
                       ``path``.
    aliases          : Alternative model names from model.json ``aliases``.
    linked_profile   : Raw "manufacturer/model" string from model.json, or
                       None.  When set, ``path`` and ``available_modes`` are
                       resolved against the linked profile's directory.
    metadata         : Raw dict from model.json (may be empty).
    """

    manufacturer: str
    requested_model: str
    canonical_model: str
    path: Path
    standby_power: float | None
    available_modes: set[str] = field(default_factory=set)
    aliases: list[str] = field(default_factory=list)
    linked_profile: str | None = None
    metadata: dict = field(default_factory=dict)

    # Convenience alias kept for backwards compatibility with calling code that
    # still reads .model - returns requested_model so behaviour is unchanged.
    @property
    def model(self) -> str:
        return self.requested_model

    def has_mode(self, mode: str) -> bool:
        return mode in self.available_modes
