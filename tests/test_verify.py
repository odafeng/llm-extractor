"""Tests for the verify stage: grounding, schema/enum, and clinical rules."""

import verify as V


def test_grounded_values_score_high():
    rec = {"pT": "T3", "nodes_exam": 15, "nodes_pos": 3, "tumor_size_cm": 3.2}
    text = "Adenocarcinoma 3.2 cm, pT3. Lymph nodes 3 of 15 positive."
    r = V.verify(rec, text)
    assert r["overall_confidence"] >= 0.9
    assert not r["needs_review"]
    assert all(d["grounded"] for d in r["fields"].values())


def test_hallucinated_number_flagged():
    # pT3 is in the text, but tumor_size_cm 9.9 is NOT -> should be flagged low
    rec = {"pT": "T3", "tumor_size_cm": 9.9}
    text = "Adenocarcinoma, pT3. No size stated clearly."
    r = V.verify(rec, text)
    assert r["fields"]["tumor_size_cm"]["grounded"] is False
    assert r["fields"]["tumor_size_cm"]["confidence"] < 0.7
    assert "tumor_size_cm" in r["review_fields"]
    assert r["needs_review"]


def test_mm_cm_twin_is_grounded():
    # report states 36 mm; extraction normalised to 3.6 cm -> still grounded
    rec = {"tumor_size_cm": 3.6}
    text = "Tumor measures 36 mm in greatest dimension."
    assert V.grounding(rec, text)["tumor_size_cm"] is True


def test_margin_grounded_when_near_keyword():
    rec = {"distal_margin_mm": 15}
    text = "Tumor is 1.5 cm from the distal resection line. Other notes 15 lymph nodes."
    assert V.grounding(rec, text)["distal_margin_mm"] is True  # 1.5 cm == 15 mm, near 'distal'


def test_margin_not_grounded_when_only_elsewhere():
    # P008-style: model put 150 in closest_margin; report says 1.5 cm by 'distal',
    # and a stray '15' exists far away — must NOT ground 150 to a margin keyword.
    rec = {"closest_margin_mm": 150}
    text = (
        "Distal resection margin: 1.5 cm, uninvolved. "
        + "x" * 200
        + " 15 mitoses per HPF noted elsewhere."
    )
    assert V.grounding(rec, text)["closest_margin_mm"] is False


def test_closest_margin_not_grounded_when_qualified():
    # 'distal resection line' specifies distal -> value belongs in distal_margin, not the
    # ambiguous closest_margin bucket; must NOT ground as closest (so it stays in review).
    rec = {"closest_margin_mm": 15}
    text = "Tumor is 1.5 cm from the distal resection line."
    assert V.grounding(rec, text)["closest_margin_mm"] is False


def test_closest_margin_grounded_when_ambiguous():
    rec = {"closest_margin_mm": 15}
    text = "Closest margin: 1.5 cm (orientation not specified)."
    assert V.grounding(rec, text)["closest_margin_mm"] is True


def test_large_margin_passes_when_grounded():
    # a 15 cm proximal/distal margin is clinically possible — magnitude must NOT flag it
    rec = {"distal_margin_mm": 150}
    text = "Distal margin is 15 cm from tumor in this long segment."
    assert V.grounding(rec, text)["distal_margin_mm"] is True


def test_off_schema_value_flagged():
    rec = {"grade": "Grade 2"}  # not in {Well, Moderate, Poor}
    text = "grade 2"
    r = V.verify(rec, text)
    assert any("off-schema" in m for m in r["flags"])
    assert r["needs_review"]


def test_rule_nodes_pos_exceeds_exam():
    rec = {"nodes_exam": 5, "nodes_pos": 8}
    r = V.verify(rec, "5 of nodes ... 8")
    assert any("impossible" in m for m in r["flags"])
    assert "nodes_pos" in r["review_fields"]


def test_rule_pN_contradicts_node_count():
    rec = {"pN": "N1a", "nodes_pos": 0, "nodes_exam": 12}
    r = V.verify(rec, "pN1a 0 of 12")
    assert any("node-positive" in m for m in r["flags"])


def test_rule_no_residual_but_grade_set():
    rec = {"tumor_found": False, "pT": "T0", "grade": "Moderate"}
    r = V.verify(rec, "ypT0 no residual tumor")
    assert any("pT0" in m or "tumor_found" in m for m in r["flags"])


def test_positive_concept_not_in_report_flagged():
    rec = {"EMVI": "Positive"}
    text = "Adenocarcinoma pT2. Margins clear."  # never mentions venous invasion
    r = V.verify(rec, text)
    assert r["fields"]["EMVI"]["confidence"] < 1.0
    assert any("not mentioned" in fl for fl in r["fields"]["EMVI"]["flags"])


def test_nulls_are_ignored():
    rec = {"pT": "T2", "EMVI": None, "CRM_dist_mm": None}
    r = V.verify(rec, "pT2")
    assert "EMVI" not in r["fields"] and "CRM_dist_mm" not in r["fields"]
