"""Schema + integrity tests for the machine-readable research ledger.

Pure (no third-party deps) so it runs in the core offline suite. Guards the
data spine that drives the dashboard Research Map + Overview verdict breakdown.
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "docs" / "research_ledger.json"
HEADLINE = REPO / "docs" / "results" / "headline.json"

VERDICTS = {"NEGATIVE", "OPEN", "INFRA", "RESOLVED", "PARKED"}
REQUIRED = {"id", "ledger_leg", "title", "where", "key_stat", "result", "verdict", "status_raw"}


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_ledger_exists_and_parses():
    assert LEDGER.exists(), "docs/research_ledger.json must be committed"
    doc = _load(LEDGER)
    assert doc.get("schema_version") == 1
    assert doc.get("source_doc") == "docs/RESEARCH_LEDGER.md"


def test_ledger_has_38_legs_with_unique_ids():
    legs = _load(LEDGER)["legs"]
    assert len(legs) == 38, f"expected 38 legs, got {len(legs)}"
    ids = [leg["id"] for leg in legs]
    assert len(set(ids)) == 38, "leg ids must be unique"
    assert sorted(ids) == list(range(1, 39)), "leg ids must be 1..38"


def test_every_leg_has_required_fields_and_valid_verdict():
    legs = _load(LEDGER)["legs"]
    for leg in legs:
        missing = REQUIRED - set(leg)
        assert not missing, f"leg {leg.get('id')} missing {missing}"
        assert leg["verdict"] in VERDICTS, f"leg {leg['id']} bad verdict {leg['verdict']}"
        assert isinstance(leg["ledger_leg"], int)
        for k in ("title", "key_stat", "result", "where"):
            assert leg[k].strip(), f"leg {leg['id']} empty {k}"


def test_verdict_breakdown_sums_to_38():
    legs = _load(LEDGER)["legs"]
    counts = {}
    for leg in legs:
        counts[leg["verdict"]] = counts.get(leg["verdict"], 0) + 1
    assert sum(counts.values()) == 38
    # the negative-result story: the plurality is CONCLUDED-NEGATIVE
    assert counts.get("NEGATIVE", 0) >= 15


def test_headline_tiles_carry_sources():
    doc = _load(HEADLINE)
    tiles = doc["tiles"]
    assert len(tiles) >= 6
    for t in tiles:
        assert t.get("source"), f"tile {t.get('key')} must cite a source"
        assert "value" in t and "label" in t
    # the protagonist number is present and small
    market = next(t for t in tiles if t["key"] == "market_implied_window_ece")
    assert market["value"] < 0.03
