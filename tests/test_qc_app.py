"""Tests for the human-QC web app: queue building + review/save/export routes.
Pure — uses a temp SQLite DB and the Flask test client; no network."""

import json

import qc_app as Q

GROUNDED = {
    "file_id": "R1",
    "report_text": "Adenocarcinoma 3.2 cm, pT3. 3 of 15 lymph nodes positive.",
    "record": {"pT": "T3", "tumor_size_cm": 3.2, "nodes_exam": 15, "nodes_pos": 3},
}
UNGROUNDED = {
    "file_id": "R2",
    "report_text": "Adenocarcinoma, pT3. No size stated.",
    "record": {"pT": "T3", "tumor_size_cm": 9.9},
}  # 9.9 not in text -> review


def _db(tmp_path):
    p = str(tmp_path / "qc.db")
    Q.build_db(p, [GROUNDED, UNGROUNDED])
    return p


def test_result_grounded_auto_vs_ungrounded_review():
    assert Q._result(GROUNDED)["decision"] == "AUTO-APPROVE"
    r = Q._result(UNGROUNDED)
    assert r["decision"] == "REVIEW"
    assert "tumor_size_cm" in r["review_fields"]


def test_build_db_splits_auto_and_pending(tmp_path):
    import sqlite3

    p = _db(tmp_path)
    c = sqlite3.connect(p)
    assert c.execute("SELECT status FROM qc WHERE sid='R1'").fetchone()[0] == "auto"
    assert c.execute("SELECT status FROM qc WHERE sid='R2'").fetchone()[0] == "pending"


def test_routes_and_save_roundtrip(tmp_path):
    import sqlite3

    p = _db(tmp_path)
    cl = Q.create_app(p).test_client()
    assert cl.get("/").status_code == 200
    assert b"R2" in cl.get("/").data  # pending one is in the queue
    assert cl.get("/r/R2").status_code == 200
    assert cl.get("/export").status_code == 200
    # correct the flagged field and save
    res = cl.post(
        "/save/R2", data={"action": "corrected", "fld_tumor_size_cm": "", "note": "no size"}
    )
    assert res.status_code == 302
    row = (
        sqlite3.connect(p)
        .execute("SELECT status, corrected, note FROM qc WHERE sid='R2'")
        .fetchone()
    )
    assert row[0] == "corrected"
    assert json.loads(row[1])["tumor_size_cm"] == ""
    assert row[2] == "no size"


# ---- Codex review fixes ----

OMITTED = {
    "file_id": "R3",
    "report_text": "Adenocarcinoma, pT3. Mismatch repair proteins retained.",
    "record": {"pT": "T3"},  # MMR omitted while report discusses it -> review-only field
}


def test_review_renders_input_for_omitted_field(tmp_path):
    p = str(tmp_path / "qc.db")
    Q.build_db(p, [OMITTED])
    html = Q.create_app(p).test_client().get("/r/R3").data.decode()
    assert "MMR" in html
    assert "fld_MMR" in html  # an editable input exists for the omitted field


def test_margins_editable_and_saved(tmp_path):
    import sqlite3

    item = {
        "file_id": "R4",
        "report_text": "CRM 1 mm, involved.",
        "record": {
            "pT": "T3",
            "margins": [
                {
                    "type": "circumferential",
                    "distance_mm": 99,
                    "involved": False,
                    "verbatim": "nope",
                }
            ],
        },
    }
    p = str(tmp_path / "qc.db")
    Q.build_db(p, [item])
    cl = Q.create_app(p).test_client()
    assert "fld_margins" in cl.get("/r/R4").data.decode()
    new = json.dumps(
        [
            {
                "type": "circumferential",
                "distance_mm": 1,
                "involved": True,
                "verbatim": "CRM 1 mm, involved",
            }
        ]
    )
    cl.post("/save/R4", data={"action": "corrected", "fld_margins": new})
    saved = sqlite3.connect(p).execute("SELECT corrected FROM qc WHERE sid='R4'").fetchone()[0]
    assert json.loads(saved)["margins"][0]["distance_mm"] == 1


def test_export_includes_record_data_for_auto_rows(tmp_path):
    import csv as _csv

    p = _db(tmp_path)  # R1 auto, R2 pending
    out = Q.create_app(p).test_client().get("/export").data.decode()
    rows = list(_csv.DictReader(out.splitlines()))
    r1 = next(r for r in rows if r["sid"] == "R1")
    assert "data" in r1 and "T3" in r1["data"]  # auto-approved row still carries its data


def test_export_blanks_pending_rows(tmp_path):
    import csv as _csv

    p = _db(tmp_path)  # R2 is pending
    out = Q.create_app(p).test_client().get("/export").data.decode()
    r2 = next(r for r in _csv.DictReader(out.splitlines()) if r["sid"] == "R2")
    assert r2["data"] == ""  # unreviewed -> not exported as final data


def test_malformed_margin_json_keeps_pending_and_preserves_edits(tmp_path):
    import sqlite3

    p = _db(tmp_path)
    cl = Q.create_app(p).test_client()
    res = cl.post(
        "/save/R2",
        data={
            "action": "corrected",
            "fld_tumor_size_cm": "7",
            "fld_margins": "{bad json,",
            "note": "wip",
        },
    )
    body = res.data.decode()
    assert res.status_code == 200  # re-rendered, not redirected away
    assert "margins JSON" in body  # error banner shown
    assert "value='7'" in body and "{bad json," in body and "wip" in body  # edits preserved
    row = sqlite3.connect(p).execute("SELECT status, corrected FROM qc WHERE sid='R2'").fetchone()
    assert row[0] == "pending" and row[1] is None  # not marked done, nothing saved
