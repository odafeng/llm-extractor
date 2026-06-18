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


def test_margin_ok_when_verbatim_and_distance_present():
    rec = {
        "margins": [
            {
                "type": "distal",
                "distance_mm": 15,
                "involved": False,
                "verbatim": "1.5 cm from distal resection line",
            }
        ]
    }
    text = "Tumor is 1.5 cm from distal resection line, uninvolved."
    r = V.verify(rec, text)
    assert not r["margin_flags"]
    assert "margins[0]" not in r["review_fields"]


def test_margin_flagged_when_verbatim_not_in_report():
    # hallucinated verbatim -> flagged
    rec = {
        "margins": [
            {
                "type": "circumferential",
                "distance_mm": 2,
                "involved": False,
                "verbatim": "CRM 2 mm clear",
            }
        ]
    }
    text = "Adenocarcinoma pT3. No margin distance stated."
    r = V.verify(rec, text)
    assert any("verbatim not found" in m for m in r["margin_flags"])
    assert "margins[0]" in r["review_fields"]


def test_margin_flagged_when_distance_not_in_its_verbatim():
    # unit/transcription error: distance_mm=150 but the verbatim says 1.5 cm
    rec = {
        "margins": [
            {
                "type": "distal",
                "distance_mm": 150,
                "involved": False,
                "verbatim": "1.5 cm from distal resection line",
            }
        ]
    }
    text = "Tumor 1.5 cm from distal resection line."
    r = V.verify(rec, text)
    assert any("does not appear in its own verbatim" in m for m in r["margin_flags"])


def test_margin_unknown_type_flagged():
    rec = {"margins": [{"type": "lateral", "distance_mm": 5, "verbatim": "lateral margin 5 mm"}]}
    r = V.verify(rec, "lateral margin 5 mm")
    assert any("unknown margin type" in m for m in r["margin_flags"])


def test_flatten_margins_derives_columns():
    margins = [
        {"type": "circumferential", "distance_mm": 2, "verbatim": "CRM 2 mm"},
        {"type": "distal", "distance_mm": 30, "verbatim": "distal 3 cm"},
    ]
    out = V.flatten_margins(margins)
    assert out["crm_distance_mm"] == 2 and out["distal_distance_mm"] == 30
    assert "CRM 2 mm" in out["margins_verbatim"] and "distal 3 cm" in out["margins_verbatim"]


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


def test_omission_flagged_when_concept_discussed_but_blank():
    # report has an MMR synoptic line but the model left MMR null -> likely omission
    rec = {"pT": "T3", "MMR": None}
    text = "Mismatch repair proteins MLH1, MSH2, MSH6, PMS2 retained. pT3."
    r = V.verify(rec, text)
    assert "MMR" in r["omissions"]
    assert "MMR" in r["review_fields"]
    assert r["needs_review"]


def test_no_omission_when_concept_absent():
    rec = {"pT": "T3", "MMR": None}
    text = "Adenocarcinoma, pT3. Margins clear."  # never mentions mismatch repair
    r = V.verify(rec, text)
    assert "MMR" not in r["omissions"]


def test_nulls_are_ignored():
    rec = {"pT": "T2", "EMVI": None, "CRM_dist_mm": None}
    r = V.verify(rec, "pT2")
    assert "EMVI" not in r["fields"] and "CRM_dist_mm" not in r["fields"]
