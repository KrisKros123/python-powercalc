"""Tests for model_json parsing and profile loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from powercalc_engine.exceptions import InvalidModelJsonError, ModelNotFoundError
from powercalc_engine.loader import find_profile_path, load_profile
from powercalc_engine.model_json import extract_standby_power, load_model_json

from tests.conftest import BRIGHTNESS_ROWS, make_profile, write_csv


# ---------------------------------------------------------------------------
# model_json tests
# ---------------------------------------------------------------------------


class TestLoadModelJson:
    def test_returns_empty_dict_when_absent(self, tmp_path):
        assert load_model_json(tmp_path) == {}

    def test_parses_standby_power(self, tmp_path):
        (tmp_path / "model.json").write_text(
            json.dumps({"standby_power": 0.5}), encoding="utf-8"
        )
        meta = load_model_json(tmp_path)
        assert meta["standby_power"] == pytest.approx(0.5)

    def test_coerces_string_standby_power(self, tmp_path):
        (tmp_path / "model.json").write_text(
            json.dumps({"standby_power": "1.2"}), encoding="utf-8"
        )
        meta = load_model_json(tmp_path)
        assert meta["standby_power"] == pytest.approx(1.2)

    def test_raises_on_invalid_json(self, tmp_path):
        (tmp_path / "model.json").write_text("not json", encoding="utf-8")
        with pytest.raises(InvalidModelJsonError, match="Invalid JSON"):
            load_model_json(tmp_path)

    def test_raises_on_array_root(self, tmp_path):
        (tmp_path / "model.json").write_text("[]", encoding="utf-8")
        with pytest.raises(InvalidModelJsonError, match="JSON object"):
            load_model_json(tmp_path)

    def test_raises_on_non_numeric_standby(self, tmp_path):
        (tmp_path / "model.json").write_text(
            json.dumps({"standby_power": "abc"}), encoding="utf-8"
        )
        with pytest.raises(InvalidModelJsonError, match="numeric"):
            load_model_json(tmp_path)

    def test_none_standby_power_stays_none(self, tmp_path):
        (tmp_path / "model.json").write_text(
            json.dumps({"standby_power": None}), encoding="utf-8"
        )
        meta = load_model_json(tmp_path)
        assert meta["standby_power"] is None

    def test_preserves_other_fields(self, tmp_path):
        data = {"standby_power": 0.3, "name": "My Bulb", "color_modes": ["hs"]}
        (tmp_path / "model.json").write_text(json.dumps(data), encoding="utf-8")
        meta = load_model_json(tmp_path)
        assert meta["name"] == "My Bulb"
        assert meta["color_modes"] == ["hs"]


class TestExtractStandbyPower:
    def test_returns_float(self):
        assert extract_standby_power({"standby_power": 0.3}) == pytest.approx(0.3)

    def test_returns_none_when_absent(self):
        assert extract_standby_power({}) is None

    def test_returns_none_when_value_is_none(self):
        assert extract_standby_power({"standby_power": None}) is None


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


class TestFindProfilePath:
    def test_exact_match(self, tmp_path):
        path = tmp_path / "signify" / "LCA001"
        path.mkdir(parents=True)
        result_path, canonical = find_profile_path(tmp_path, "signify", "LCA001")
        assert result_path == path
        assert canonical == "LCA001"

    def test_case_insensitive_manufacturer(self, tmp_path):
        path = tmp_path / "signify" / "LCA001"
        path.mkdir(parents=True)
        result_path, canonical = find_profile_path(tmp_path, "SIGNIFY", "LCA001")
        assert result_path == path
        assert canonical == "LCA001"

    def test_case_insensitive_model(self, tmp_path):
        path = tmp_path / "signify" / "LCA001"
        path.mkdir(parents=True)
        result_path, canonical = find_profile_path(tmp_path, "signify", "lca001")
        assert result_path == path
        assert canonical == "LCA001"

    def test_raises_when_not_found(self, tmp_path):
        with pytest.raises(ModelNotFoundError):
            find_profile_path(tmp_path, "noone", "NOTHING")


class TestLoadProfile:
    def test_loads_standby_power(self, tmp_path):
        make_profile(tmp_path, standby_power=1.5, modes=("brightness",))
        profile = load_profile(tmp_path, "acme", "BULB001")
        assert profile.standby_power == pytest.approx(1.5)

    def test_standby_power_none_when_absent(self, tmp_path):
        make_profile(tmp_path, standby_power=None, modes=("brightness",))
        profile = load_profile(tmp_path, "acme", "BULB001")
        assert profile.standby_power is None

    def test_detects_available_modes(self, tmp_path):
        make_profile(tmp_path, modes=("brightness", "color_temp", "hs"))
        profile = load_profile(tmp_path, "acme", "BULB001")
        assert "brightness" in profile.available_modes
        assert "color_temp" in profile.available_modes
        assert "hs" in profile.available_modes
        assert "effect" not in profile.available_modes

    def test_detects_gz_modes(self, tmp_path):
        make_profile(tmp_path, modes=("brightness",), gz=True)
        profile = load_profile(tmp_path, "acme", "BULB001")
        assert "brightness" in profile.available_modes

    def test_profile_path_correct(self, tmp_path):
        make_profile(tmp_path, modes=("brightness",))
        profile = load_profile(tmp_path, "acme", "BULB001")
        assert profile.path == tmp_path / "acme" / "BULB001"

    def test_missing_model_raises(self, tmp_path):
        with pytest.raises(ModelNotFoundError):
            load_profile(tmp_path, "nonexistent", "MODEL")

    def test_metadata_preserved(self, tmp_path):
        profile_dir = tmp_path / "acme" / "BULB001"
        profile_dir.mkdir(parents=True)
        meta = {"standby_power": 0.4, "name": "Test Bulb", "supported_colors": ["hs"]}
        (profile_dir / "model.json").write_text(json.dumps(meta), encoding="utf-8")
        write_csv(profile_dir / "brightness.csv", BRIGHTNESS_ROWS)
        profile = load_profile(tmp_path, "acme", "BULB001")
        assert profile.metadata["name"] == "Test Bulb"
        assert profile.metadata["supported_colors"] == ["hs"]
