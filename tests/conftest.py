"""Shared pytest fixtures and CSV generation helpers.

Every fixture that builds a fake profile library writes its files into the
``tmp_path`` directory provided by pytest so tests remain fully isolated.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Low-level CSV writers
# ---------------------------------------------------------------------------


def write_csv(path: Path, rows: list[list]) -> None:
    """Write *rows* (including header) as a plain CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def write_csv_gz(path: Path, rows: list[list]) -> None:
    """Write *rows* as a gzip-compressed CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
        fh.write(buf.getvalue())


def write_model_json(path: Path, data: dict) -> None:
    """Write *data* as model.json inside directory *path*."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "model.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Sample LUT data
# ---------------------------------------------------------------------------

BRIGHTNESS_ROWS = [
    ["bri", "watt"],
    [0, 0.4],
    [128, 9.0],
    [255, 18.0],
]

COLOR_TEMP_ROWS = [
    ["bri", "mired", "watt"],
    [0, 153, 0.4],
    [0, 370, 0.5],
    [255, 153, 9.5],
    [255, 370, 12.0],
]

HS_ROWS = [
    ["bri", "hue", "sat", "watt"],
    [0,   0,     0,   0.4],
    [0,   0,   255,   0.5],
    [0,   32768, 0,   0.5],
    [0,   32768, 255, 0.6],
    [255, 0,     0,   9.0],
    [255, 0,   255,  10.0],
    [255, 32768, 0,  10.0],
    [255, 32768, 255, 11.0],
]

EFFECT_ROWS = [
    ["effect", "bri", "watt"],
    ["candle", 0,   0.5],
    ["candle", 255, 8.0],
    ["fireplace", 0,   0.6],
    ["fireplace", 255, 9.0],
]


# ---------------------------------------------------------------------------
# Profile builder
# ---------------------------------------------------------------------------


def make_profile(
    base_dir: Path,
    manufacturer: str = "acme",
    model: str = "BULB001",
    *,
    standby_power: float | None = None,
    modes: tuple[str, ...] = ("brightness",),
    gz: bool = False,
) -> Path:
    """Create a minimal profile directory for *manufacturer*/*model*.

    Parameters
    ----------
    base_dir     : Root of the fake profile library (e.g. ``tmp_path``).
    manufacturer : Manufacturer name.
    model        : Model name.
    standby_power: Value to write into model.json, or None to omit the field.
    modes        : Tuple of LUT mode names to create CSV files for.
    gz           : If True, write ``.csv.gz``; otherwise write ``.csv``.

    Returns
    -------
    Path to the profile directory.
    """
    profile_dir = base_dir / manufacturer / model
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Write model.json.
    meta: dict = {}
    if standby_power is not None:
        meta["standby_power"] = standby_power
    (profile_dir / "model.json").write_text(json.dumps(meta), encoding="utf-8")

    _mode_rows: dict[str, list[list]] = {
        "brightness": BRIGHTNESS_ROWS,
        "color_temp": COLOR_TEMP_ROWS,
        "hs": HS_ROWS,
        "effect": EFFECT_ROWS,
    }

    writer = write_csv_gz if gz else write_csv
    ext = ".csv.gz" if gz else ".csv"

    for mode in modes:
        rows = _mode_rows[mode]
        writer(profile_dir / f"{mode}{ext}", rows)

    return profile_dir


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def profile_dir(tmp_path: Path) -> Path:
    """Return a temporary profile library root (empty)."""
    return tmp_path


@pytest.fixture()
def brightness_profile(tmp_path: Path) -> tuple[Path, Path]:
    """(library_root, profile_path) with brightness.csv and standby_power=0.3."""
    make_profile(tmp_path, standby_power=0.3, modes=("brightness",))
    return tmp_path, tmp_path / "acme" / "BULB001"


@pytest.fixture()
def color_temp_profile(tmp_path: Path) -> tuple[Path, Path]:
    """(library_root, profile_path) with color_temp.csv and standby_power=0.3."""
    make_profile(tmp_path, standby_power=0.3, modes=("color_temp",))
    return tmp_path, tmp_path / "acme" / "BULB001"


@pytest.fixture()
def hs_profile(tmp_path: Path) -> tuple[Path, Path]:
    """(library_root, profile_path) with hs.csv and standby_power=0.3."""
    make_profile(tmp_path, standby_power=0.3, modes=("hs",))
    return tmp_path, tmp_path / "acme" / "BULB001"


@pytest.fixture()
def effect_profile(tmp_path: Path) -> tuple[Path, Path]:
    """(library_root, profile_path) with effect.csv and standby_power=0.3."""
    make_profile(tmp_path, standby_power=0.3, modes=("effect", "brightness"))
    return tmp_path, tmp_path / "acme" / "BULB001"


@pytest.fixture()
def gz_profile(tmp_path: Path) -> tuple[Path, Path]:
    """(library_root, profile_path) with brightness.csv.gz."""
    make_profile(tmp_path, standby_power=0.5, modes=("brightness",), gz=True)
    return tmp_path, tmp_path / "acme" / "BULB001"
