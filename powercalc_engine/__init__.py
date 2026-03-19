"""powercalc_engine - standalone powercalc LUT library.

Public surface
--------------
>>> from powercalc_engine import PowercalcEngine
>>> engine = PowercalcEngine(profile_dir="profile_library")
>>> watts = engine.get_power(
...     manufacturer="signify",
...     model="LCA001",
...     state={
...         "is_on": True,
...         "brightness": 180,
...         "color_mode": "hs",
...         "hue": 24000,
...         "saturation": 180,
...         "color_temp": None,
...         "effect": None,
...     },
... )
"""

from .engine import PowercalcEngine
from .exceptions import (
    InvalidModelJsonError,
    LutCalculationError,
    MissingLookupTableError,
    ModelNotFoundError,
    PowercalcError,
)
from .models import DeviceState, ModelProfile

__all__ = [
    "PowercalcEngine",
    "DeviceState",
    "ModelProfile",
    "PowercalcError",
    "ModelNotFoundError",
    "MissingLookupTableError",
    "InvalidModelJsonError",
    "LutCalculationError",
]

__version__ = "0.1.0"
