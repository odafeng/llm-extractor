"""Tests for the ensemble QC layer: cross-model agreement merged with grounding verify.
All pure (no network) — they exercise consensus() and ensemble_verdict() on inline records."""

import ensemble as E

GROUNDED = {"pT": "T3", "nodes_exam": 15, "nodes_pos": 3, "tumor_size_cm": 3.2}
TEXT = "Adenocarcinoma 3.2 cm, pT3. Lymph nodes 3 of 15 positive."


def test_all_agree_and_grounded_auto_approves():
    recs = [dict(GROUNDED) for _ in range(3)]
    v = E.ensemble_verdict(recs, TEXT)
    assert v["decision"] == "AUTO-APPROVE"
    assert v["models_agree"] and not v["needs_review"]
    assert v["disagree_fields"] == []
    assert v["n_models"] == 3


def test_disagreement_flags_the_field():
    recs = [dict(GROUNDED), dict(GROUNDED), {**GROUNDED, "pT": "T2"}]
    v = E.ensemble_verdict(recs, TEXT)
    assert "pT" in v["disagree_fields"]
    assert v["decision"] == "REVIEW" and v["needs_review"]
    assert "pT" in v["review_fields"]


def test_grounding_catches_what_ensemble_misses():
    # all 3 models agree on a hallucinated size (9.9 cm not in text) -> models agree,
    # but grounding flags it -> still REVIEW.
    rec = {"pT": "T3", "tumor_size_cm": 9.9}
    recs = [dict(rec) for _ in range(3)]
    v = E.ensemble_verdict(recs, "Adenocarcinoma, pT3. No size stated.")
    assert v["models_agree"] is True
    assert v["disagree_fields"] == []
    assert v["needs_review"] and v["decision"] == "REVIEW"
    assert "tumor_size_cm" in v["review_fields"]


def test_consensus_margins_compared_by_closest():
    recs = [
        {"margins": [{"type": "distal", "distance_mm": 5, "verbatim": "5 mm distal"}]},
        {"margins": [{"type": "distal", "distance_mm": 12, "verbatim": "12 mm distal"}]},
    ]
    cons = E.consensus(recs)
    assert cons["margins"]["agree"] is False
    # same closest -> agree
    same = [
        {"margins": [{"type": "distal", "distance_mm": 5, "verbatim": "a"}]},
        {"margins": [{"type": "distal", "distance_mm": 5, "verbatim": "b"}]},
    ]
    assert E.consensus(same)["margins"]["agree"] is True


def test_file_id_and_notes_ignored_in_consensus():
    recs = [
        {"pT": "T3", "file_id": "P001", "extraction_notes": "foo"},
        {"pT": "T3", "file_id": "P002", "extraction_notes": "bar"},
    ]
    cons = E.consensus(recs)
    assert "file_id" not in cons and "extraction_notes" not in cons
    assert cons["pT"]["agree"] is True


def test_empty_records_raises():
    import pytest

    with pytest.raises(ValueError):
        E.ensemble_verdict([], TEXT)
