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
