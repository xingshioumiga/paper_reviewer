"""Unit tests for glossary_merge helpers."""

from pathlib import Path

from glossary_merge import (
    load_initial_glossary_state,
    merge_glossary_candidates,
    normalize_abbr_key,
    save_merged_yaml,
)


def test_normalize_abbr_key_uppercases() -> None:
    assert normalize_abbr_key(" ev ") == "EV"
    assert normalize_abbr_key("hhg") == "HHG"


def test_merge_respects_locked() -> None:
    locked = {"EV": "ellipticity-varying"}
    provisional: dict[str, str] = {}
    entries = [{"abbr": "EV", "expansion": "wrong expansion", "confidence": 0.99}]
    new_p, logs = merge_glossary_candidates(locked, provisional, entries)
    assert "EV" not in new_p
    assert any("locked" in x for x in logs)


def test_merge_adds_provisional() -> None:
    locked: dict[str, str] = {}
    provisional: dict[str, str] = {}
    entries = [{"abbr": "HHG", "expansion": "high-order harmonic generation", "confidence": 0.8}]
    new_p, _ = merge_glossary_candidates(locked, provisional, entries)
    assert new_p.get("HHG") == "high-order harmonic generation"


def test_merge_conflict_keeps_first_provisional() -> None:
    locked: dict[str, str] = {}
    provisional = {"ROM": "relativistic oscillating mirror"}
    entries = [{"abbr": "ROM", "expansion": "completely different gloss", "confidence": 0.9}]
    new_p, logs = merge_glossary_candidates(locked, provisional, entries)
    assert new_p["ROM"] == "relativistic oscillating mirror"
    assert any("conflict" in x for x in logs)


def test_load_initial_glossary_state_roundtrip(tmp_path: Path) -> None:
    seed = tmp_path / "seed.yaml"
    seed.write_text(
        "locked:\n  EV: ellipticity-varying\n",
        encoding="utf-8",
    )
    merged = tmp_path / "merged.yaml"
    save_merged_yaml(merged, {"EV": "ellipticity-varying"}, {"HHG": "high-order harmonic generation"})
    locked, prov = load_initial_glossary_state(seed, merged, load_provisional_from_merged=True)
    assert locked["EV"] == "ellipticity-varying"
    assert prov.get("HHG") == "high-order harmonic generation"
