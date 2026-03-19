"""Tests for alias-based lookup, linked_profile chain, and canonical_model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from powercalc_engine import ModelNotFoundError, PowercalcEngine
from powercalc_engine.exceptions import InvalidModelJsonError
from powercalc_engine.loader import load_profile
from powercalc_engine.model_json import extract_aliases, extract_linked_profile

from tests.conftest import BRIGHTNESS_ROWS, write_csv


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_model_dir(
    base: Path,
    manufacturer: str,
    model: str,
    meta: dict,
    lut_rows: list | None = None,
) -> Path:
    d = base / manufacturer / model
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.json").write_text(json.dumps(meta), encoding="utf-8")
    if lut_rows:
        write_csv(d / "brightness.csv", lut_rows)
    return d


# ---------------------------------------------------------------------------
# model_json extraction
# ---------------------------------------------------------------------------


class TestExtractAliases:
    def test_list_of_strings(self):
        assert extract_aliases({"aliases": ["ABC123", "XYZ999"]}) == ["ABC123", "XYZ999"]

    def test_single_string_normalised_to_list(self):
        assert extract_aliases({"aliases": "SINGLE"}) == ["SINGLE"]

    def test_absent_returns_empty(self):
        assert extract_aliases({}) == []

    def test_none_value_returns_empty(self):
        assert extract_aliases({"aliases": None}) == []

    def test_unexpected_type_returns_empty(self):
        assert extract_aliases({"aliases": 42}) == []


class TestExtractLinkedProfile:
    def test_full_path(self):
        assert extract_linked_profile({"linked_profile": "signify/LCA001"}) == "signify/LCA001"

    def test_model_only(self):
        assert extract_linked_profile({"linked_profile": "LCA001"}) == "LCA001"

    def test_absent_returns_none(self):
        assert extract_linked_profile({}) is None

    def test_none_value_returns_none(self):
        assert extract_linked_profile({"linked_profile": None}) is None

    def test_empty_string_returns_none(self):
        assert extract_linked_profile({"linked_profile": ""}) is None

    def test_strips_whitespace(self):
        assert extract_linked_profile({"linked_profile": "  signify/LCA001  "}) == "signify/LCA001"


# ---------------------------------------------------------------------------
# Alias lookup
# ---------------------------------------------------------------------------


class TestAliasLookup:
    def test_find_model_by_alias(self, tmp_path):
        make_model_dir(
            tmp_path, "signify", "LCA001",
            meta={"standby_power": 0.3, "aliases": ["LCA001X", "9290022267"]},
            lut_rows=BRIGHTNESS_ROWS,
        )
        profile = load_profile(tmp_path, "signify", "LCA001X")
        assert profile.requested_model == "LCA001X"
        assert profile.canonical_model == "LCA001"
        assert profile.path == tmp_path / "signify" / "LCA001"

    def test_alias_case_insensitive(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001",
                       meta={"aliases": ["MyAlias"]}, lut_rows=BRIGHTNESS_ROWS)
        profile = load_profile(tmp_path, "signify", "myalias")
        assert profile.canonical_model == "LCA001"

    def test_alias_returns_correct_standby(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001",
                       meta={"standby_power": 0.4, "aliases": ["9290022267"]},
                       lut_rows=BRIGHTNESS_ROWS)
        engine = PowercalcEngine(tmp_path)
        assert engine.get_power("signify", "9290022267", state={"is_on": False}) == pytest.approx(0.4)

    def test_non_alias_raises(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001",
                       meta={"aliases": ["LCA001X"]}, lut_rows=BRIGHTNESS_ROWS)
        with pytest.raises(ModelNotFoundError):
            load_profile(tmp_path, "signify", "NONEXISTENT")

    def test_aliases_stored_on_profile(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001",
                       meta={"aliases": ["A", "B", "C"]}, lut_rows=BRIGHTNESS_ROWS)
        profile = load_profile(tmp_path, "signify", "LCA001")
        assert set(profile.aliases) == {"A", "B", "C"}

    def test_broken_model_json_in_alias_scan_raises_invalid(self, tmp_path):
        """InvalidModelJsonError must NOT be swallowed during the alias scan."""
        (tmp_path / "signify").mkdir(parents=True)
        bad_dir = tmp_path / "signify" / "BROKEN"
        bad_dir.mkdir()
        (bad_dir / "model.json").write_text("not json", encoding="utf-8")
        with pytest.raises(InvalidModelJsonError):
            load_profile(tmp_path, "signify", "SOMETHING")


# ---------------------------------------------------------------------------
# canonical_model vs requested_model
# ---------------------------------------------------------------------------


class TestCanonicalModel:
    def test_direct_lookup_canonical_equals_requested(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001", meta={}, lut_rows=BRIGHTNESS_ROWS)
        profile = load_profile(tmp_path, "signify", "LCA001")
        assert profile.requested_model == "LCA001"
        assert profile.canonical_model == "LCA001"

    def test_alias_lookup_canonical_is_dir_name(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001",
                       meta={"aliases": ["LCA001X"]}, lut_rows=BRIGHTNESS_ROWS)
        profile = load_profile(tmp_path, "signify", "LCA001X")
        assert profile.requested_model == "LCA001X"   # what caller passed
        assert profile.canonical_model == "LCA001"    # actual directory name

    def test_model_property_returns_requested(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001",
                       meta={"aliases": ["LCA001X"]}, lut_rows=BRIGHTNESS_ROWS)
        profile = load_profile(tmp_path, "signify", "LCA001X")
        # .model is a backwards-compat alias for requested_model
        assert profile.model == "LCA001X"


# ---------------------------------------------------------------------------
# linked_profile — single hop
# ---------------------------------------------------------------------------


class TestLinkedProfile:
    def test_lut_from_linked_profile(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001", meta={"standby_power": 0.3},
                       lut_rows=BRIGHTNESS_ROWS)
        make_model_dir(tmp_path, "signify", "LCA002",
                       meta={"standby_power": 0.5, "linked_profile": "signify/LCA001"})
        profile = load_profile(tmp_path, "signify", "LCA002")
        assert profile.path == tmp_path / "signify" / "LCA001"
        assert profile.standby_power == pytest.approx(0.5)
        assert profile.linked_profile == "signify/LCA001"
        assert "brightness" in profile.available_modes

    def test_power_calculation_uses_linked_lut(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001", meta={}, lut_rows=BRIGHTNESS_ROWS)
        make_model_dir(tmp_path, "signify", "LCA002",
                       meta={"standby_power": 0.9, "linked_profile": "signify/LCA001"})
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power("signify", "LCA002",
                                  state={"is_on": True, "brightness": 255, "color_mode": "brightness"})
        assert watts == pytest.approx(18.0)

    def test_standby_from_own_model_not_linked(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001",
                       meta={"standby_power": 99.9}, lut_rows=BRIGHTNESS_ROWS)
        make_model_dir(tmp_path, "signify", "LCA002",
                       meta={"standby_power": 0.7, "linked_profile": "signify/LCA001"})
        engine = PowercalcEngine(tmp_path)
        assert engine.get_power("signify", "LCA002", state={"is_on": False}) == pytest.approx(0.7)

    def test_model_only_linked_resolves_same_manufacturer(self, tmp_path):
        make_model_dir(tmp_path, "acme", "BASE", meta={}, lut_rows=BRIGHTNESS_ROWS)
        make_model_dir(tmp_path, "acme", "VARIANT", meta={"linked_profile": "BASE"})
        profile = load_profile(tmp_path, "acme", "VARIANT")
        assert profile.path == tmp_path / "acme" / "BASE"

    def test_broken_linked_profile_raises(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA002",
                       meta={"linked_profile": "signify/NONEXISTENT"})
        with pytest.raises(ModelNotFoundError, match="linked_profile"):
            load_profile(tmp_path, "signify", "LCA002")

    def test_no_linked_profile_is_none(self, tmp_path):
        make_model_dir(tmp_path, "signify", "LCA001", meta={}, lut_rows=BRIGHTNESS_ROWS)
        profile = load_profile(tmp_path, "signify", "LCA001")
        assert profile.linked_profile is None


# ---------------------------------------------------------------------------
# linked_profile — multi-hop chain  A → B → C
# ---------------------------------------------------------------------------


class TestLinkedProfileChain:
    def test_chain_a_to_b_to_c(self, tmp_path):
        """A links to B which links to C (real LUTs).  Path must resolve to C."""
        make_model_dir(tmp_path, "acme", "C", meta={"standby_power": 1.0},
                       lut_rows=BRIGHTNESS_ROWS)
        make_model_dir(tmp_path, "acme", "B", meta={"standby_power": 2.0,
                                                      "linked_profile": "acme/C"})
        make_model_dir(tmp_path, "acme", "A", meta={"standby_power": 3.0,
                                                      "linked_profile": "acme/B"})

        profile = load_profile(tmp_path, "acme", "A")
        assert profile.path == tmp_path / "acme" / "C"   # terminal LUT dir
        assert profile.standby_power == pytest.approx(3.0)  # from A's own model.json
        assert "brightness" in profile.available_modes

    def test_chain_power_calculated_from_terminal_lut(self, tmp_path):
        make_model_dir(tmp_path, "acme", "C", meta={}, lut_rows=BRIGHTNESS_ROWS)
        make_model_dir(tmp_path, "acme", "B", meta={"linked_profile": "acme/C"})
        make_model_dir(tmp_path, "acme", "A", meta={"standby_power": 0.5,
                                                      "linked_profile": "acme/B"})
        engine = PowercalcEngine(tmp_path)
        watts = engine.get_power("acme", "A",
                                  state={"is_on": True, "brightness": 255, "color_mode": "brightness"})
        assert watts == pytest.approx(18.0)

    def test_chain_depth_exceeded_raises(self, tmp_path):
        """Chain longer than _MAX_LINK_DEPTH must raise ModelNotFoundError."""
        # Build a chain of 7 nodes: 0 → 1 → 2 → … → 6 (no terminal LUT)
        for i in range(7):
            next_model = f"M{i + 1}" if i < 6 else None
            meta = {"linked_profile": f"acme/M{i + 1}"} if next_model else {}
            make_model_dir(tmp_path, "acme", f"M{i}", meta=meta)

        with pytest.raises(ModelNotFoundError, match="exceeds maximum depth"):
            load_profile(tmp_path, "acme", "M0")
