"""Human-QC web interface for the extraction pipeline.

Builds a SQLite review queue from extracted records (running ``verify`` — or
``ensemble_verdict`` when several model records are supplied per report) and serves a browser
UI: the reviewer sees the source report beside the extracted fields with per-field
confidence / grounding / flags / cross-model disagreement, then Approves / Corrects /
Rejects. Decisions persist to the SQLite DB, which doubles as a queryable QC'd cohort table;
``/export`` downloads it as CSV.

Pure data layer (``build_db``) + app factory (``create_app``) are network-free and
unit-tested; only feeding it multi-model records (or the live pipeline) touches Ollama.

Input (JSONL or JSON list), one item per report:
    {"file_id": "R001", "report_text": "...", "record": {...}}            # single model
    {"file_id": "R001", "report_text": "...", "records": [{...}, {...}]}   # ensemble

Run:  python qc_app.py records.jsonl            # builds qc.db (if absent) + serves :8050
Open: http://<host>:8050/    NOTE: serves report text (possible PHI) — trusted network only.
"""

import csv
import html
import io
import json
import re
import sqlite3
from datetime import UTC, datetime

from flask import Flask, g, redirect, request, send_file, url_for

import verify as V
from ensemble import ensemble_verdict


def _result(item: dict) -> dict:
    """Compute the QC result for one report item (no network)."""
    text = item.get("report_text", "")
    if item.get("records"):
        v = ensemble_verdict(item["records"], text)
        rec, review_fields = v["record"], v["review_fields"]
        decision, needs = v["decision"], v["needs_review"]
        ver = V.verify(rec, text)
    else:
        rec = item.get("record", {})
        ver = V.verify(rec, text)
        review_fields, needs = ver["review_fields"], ver["needs_review"]
        decision = "REVIEW" if needs else "AUTO-APPROVE"
    return {
        "record": rec,
        "verify": ver,
        "decision": decision,
        "needs_review": needs,
        "review_fields": review_fields,
        "text": text,
    }


def build_db(db_path: str, items: list[dict]) -> None:
    c = sqlite3.connect(db_path)
    c.execute("""CREATE TABLE IF NOT EXISTS qc(
        sid TEXT PRIMARY KEY, report_text TEXT, record TEXT, verify TEXT,
        decision TEXT, review_fields TEXT, status TEXT DEFAULT 'pending',
        corrected TEXT, note TEXT, reviewed_at TEXT)""")
    for i, it in enumerate(items):
        r = _result(it)
        sid = str(it.get("file_id") or it.get("sid") or f"R{i:04d}")
        status = "pending" if r["needs_review"] else "auto"
        c.execute(
            "INSERT OR REPLACE INTO qc(sid,report_text,record,verify,decision,"
            "review_fields,status) VALUES(?,?,?,?,?,?,?)",
            (
                sid,
                r["text"],
                json.dumps(r["record"], ensure_ascii=False),
                json.dumps(r["verify"], ensure_ascii=False),
                r["decision"],
                json.dumps(r["review_fields"]),
                status,
            ),
        )
    c.commit()
    c.close()


def _load_items(path: str) -> list[dict]:
    raw = open(path, encoding="utf-8").read().strip()
    if raw.startswith("["):
        return json.loads(raw)
    return [json.loads(ln) for ln in raw.splitlines() if ln.strip()]


CSS = """<style>
body{font-family:-apple-system,'Segoe UI','PingFang TC',sans-serif;margin:0;background:#f4f5f7;color:#1c2128}
a{color:#2563c9;text-decoration:none}.wrap{max-width:1180px;margin:0 auto;padding:16px}
.bar{background:#1f2330;color:#fff;padding:12px 18px}.bar b{color:#7ee0a8}.bar a{color:#cde;margin-left:16px}
.card{display:inline-block;background:#fff;border:1px solid #dde;border-radius:8px;padding:10px 16px;margin:6px 8px 6px 0}
.card b{font-size:22px;display:block}table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #dde;border-radius:8px}
th,td{padding:7px 10px;border-bottom:1px solid #eee;text-align:left;font-size:13px}th{background:#f0f2f6}
tr:hover{background:#f7fbff}.tag{padding:2px 8px;border-radius:10px;font-size:12px;font-weight:700}
.rev{background:#ffe0cc;color:#9a4a17}.auto{background:#d7f0cf;color:#256b1f}
.rep{display:flex;gap:16px}.txt{flex:1.5;white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:12.5px;
line-height:1.5;background:#fff;border:1px solid #dde;border-radius:8px;padding:12px;max-height:80vh;overflow:auto}
.side{flex:1.2}.box{background:#fff;border:1px solid #dde;border-radius:8px;padding:12px;margin-bottom:12px}
mark{background:#fff3a0}.bad{color:#c0392b;font-weight:700}.ok{color:#256b1f}
input,select,textarea{font:inherit;padding:5px;border:1px solid #ccd;border-radius:6px;width:100%}
label{font-size:12px;color:#555}button{background:#2563c9;color:#fff;border:0;border-radius:7px;padding:10px 18px;font-weight:700;cursor:pointer}
.fl{color:#9a4a17;font-size:12px}
</style>"""


def _page(body: str) -> str:
    return (
        f"<!doctype html><meta charset=utf-8><title>QC</title>{CSS}"
        f"<div class=bar><b>Extraction QC</b><a href='/'>Queue</a><a href='/export'>Export CSV</a></div>"
        f"<div class=wrap>{body}</div>"
    )


def _highlight(text: str, values: list[str]) -> str:
    esc = html.escape(text or "")
    for v in sorted({str(x) for x in values if x not in (None, "")}, key=len, reverse=True):
        ev = html.escape(v)
        if ev and ev.lower() in esc.lower():
            esc = re.sub(re.escape(ev), f"<mark>{ev}</mark>", esc, flags=re.IGNORECASE)
    return esc


def create_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(db_path)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def _close(_):
        d = g.pop("db", None)
        if d:
            d.close()

    @app.route("/")
    def index():
        c = db()
        n = {
            k: c.execute(f"SELECT COUNT(*) FROM qc WHERE {w}").fetchone()[0]
            for k, w in {
                "auto": "status='auto'",
                "pending": "status='pending'",
                "done": "status IN('approved','corrected','rejected')",
            }.items()
        }
        rows = c.execute("SELECT * FROM qc WHERE status='pending' ORDER BY sid").fetchall()
        cards = (
            f"<div class=card>auto-approved<b>{n['auto']}</b></div>"
            f"<div class=card>review pending<b style='color:#c0392b'>{n['pending']}</b></div>"
            f"<div class=card>reviewed<b style='color:#256b1f'>{n['done']}</b></div>"
        )
        tr = "".join(
            f"<tr onclick=\"location='/r/{r['sid']}'\" style=cursor:pointer><td><b>{r['sid']}</b></td>"
            f"<td class=fl>{' · '.join(json.loads(r['review_fields']))}</td></tr>"
            for r in rows
        )
        table = (
            f"<h3>Review queue ({n['pending']})</h3><table><tr><th>report</th>"
            f"<th>fields to check</th></tr>{tr}</table>"
            if rows
            else "<h3>✅ Queue empty — all reviewed.</h3>"
        )
        return _page(cards + "<div style=margin:14px></div>" + table)

    def _render(sid, overrides=None, margins_raw=None, note=None, err=""):
        """Render the review page. On a failed save, `overrides`/`margins_raw`/`note` carry
        the reviewer's just-submitted edits so nothing is lost while the row stays pending."""
        overrides = overrides or {}
        c = db()
        r = c.execute("SELECT * FROM qc WHERE sid=?", (sid,)).fetchone()
        if not r:
            return redirect(url_for("index"))
        rec = json.loads(r["record"])
        ver = json.loads(r["verify"])
        review_fields = set(json.loads(r["review_fields"]))
        # field rows over the UNION of extracted keys and flagged review fields, so omitted
        # fields (blank in the record, or only found by another model) still get an input.
        scalar = [k for k in rec if not k.startswith("_") and k != "margins"]
        extra = [
            f
            for f in sorted(review_fields)
            if f not in scalar and f != "margins" and not f.startswith("margins")
        ]
        rows = ""
        for f in scalar + extra:
            v = overrides.get(f, rec.get(f, ""))
            fd = ver.get("fields", {}).get(f, {})
            conf = fd.get("confidence")
            flags = "; ".join(fd.get("flags", []))
            flag_me = f in review_fields or f in extra
            cls = "bad" if flag_me else "ok"
            inp = (
                f"<input name='fld_{f}' value='{html.escape(str(v))}'>"
                if flag_me
                else html.escape(str(v))
            )
            rows += (
                f"<tr><td class={cls}>{f}</td><td>{inp}</td>"
                f"<td>{'' if conf is None else conf}</td><td class=fl>{html.escape(flags)}</td></tr>"
            )
        # margins: show why flagged + make the list editable (JSON), so margin QC is completable
        margins = rec.get("margins")
        mflags = ver.get("margin_flags", [])
        margin_flagged = bool(mflags) or any(str(f).startswith("margins") for f in review_fields)
        mrow = ""
        if margins is not None or margin_flagged or margins_raw is not None:
            mj = (
                html.escape(margins_raw)
                if margins_raw is not None
                else html.escape(json.dumps(margins or [], ensure_ascii=False, indent=1))
            )
            flag_txt = f"<div class=fl>{html.escape('; '.join(mflags))}</div>" if mflags else ""
            mrow = (
                f"<tr><td class={'bad' if margin_flagged else 'ok'}>margins</td>"
                f"<td colspan=3>{flag_txt}<textarea name=fld_margins rows=4>{mj}</textarea></td></tr>"
            )
        note_val = note if note is not None else (r["note"] or "")
        controls = (
            "<label>Decision</label>"
            "<select name=action><option value=approved>✅ Approve</option>"
            "<option value=corrected>✏️ Correct (edits above)</option>"
            "<option value=rejected>❌ Reject / indeterminate</option></select>"
            f"<label>note</label><textarea name=note rows=2>{html.escape(note_val)}</textarea>"
            "<div style=margin-top:10px><button>Save → next</button></div>"
        )
        values = [v for k, v in rec.items() if not k.startswith("_") and k != "margins"]
        banner = (
            "<div class=box style='border-color:#c0392b;color:#c0392b'>"
            "⚠️ margins JSON 無法解析 —— 未儲存,你剛剛的編輯已保留,請修正後再存。</div>"
            if err == "margins"
            else ""
        )
        # one <form> wrapping the editable field/margin inputs AND the controls, so edits submit
        side = (
            banner + f"<div class=box><b>{sid}</b> <span class='tag rev'>{r['decision']}</span>"
            f"<div class=fl>check: {' · '.join(sorted(review_fields))}</div></div>"
            f"<form method=post action='/save/{sid}'>"
            f"<div class=box><table><tr><th>field</th><th>value</th><th>conf</th><th>flags</th></tr>"
            f"{rows}{mrow}</table></div><div class=box>{controls}</div></form>"
        )
        return _page(
            f"<p><a href='/'>← queue</a></p><div class=rep>"
            f"<div class=txt>{_highlight(r['report_text'], values)}</div>"
            f"<div class=side>{side}</div></div>"
        )

    @app.route("/r/<sid>")
    def review(sid):
        return _render(sid)

    @app.route("/save/<sid>", methods=["POST"])
    def save(sid):
        c = db()
        r = c.execute("SELECT record FROM qc WHERE sid=?", (sid,)).fetchone()
        if not r:
            return redirect(url_for("index"))
        rec = json.loads(r["record"])
        for k, val in request.form.items():
            if k == "fld_margins":
                try:
                    rec["margins"] = json.loads(val)
                except json.JSONDecodeError:
                    # don't silently drop edits + mark the case done — re-render with the
                    # reviewer's submitted values preserved, row stays pending.
                    overrides = {
                        kk[4:]: vv
                        for kk, vv in request.form.items()
                        if kk.startswith("fld_") and kk != "fld_margins"
                    }
                    return _render(
                        sid,
                        overrides=overrides,
                        margins_raw=val,
                        note=request.form.get("note", ""),
                        err="margins",
                    )
            elif k.startswith("fld_"):
                rec[k[4:]] = val
        c.execute(
            "UPDATE qc SET status=?, corrected=?, note=?, reviewed_at=? WHERE sid=?",
            (
                request.form.get("action", "approved"),
                json.dumps(rec, ensure_ascii=False),
                request.form.get("note", ""),
                datetime.now(UTC).isoformat(timespec="seconds"),
                sid,
            ),
        )
        c.commit()
        nxt = c.execute("SELECT sid FROM qc WHERE status='pending' ORDER BY sid LIMIT 1").fetchone()
        return redirect(url_for("review", sid=nxt["sid"]) if nxt else url_for("index"))

    @app.route("/export")
    def export():
        c = db()
        rows = c.execute("SELECT * FROM qc ORDER BY sid").fetchall()
        buf = io.StringIO()
        w = csv.writer(buf)
        # `data` = the trustworthy final record only: human-corrected if reviewed, the raw
        # extraction for auto-approved rows, BLANK for still-pending rows (so unreviewed
        # flagged values are never exported as if final).
        cols = ["sid", "decision", "status", "review_fields", "note", "reviewed_at"]
        w.writerow(cols + ["data"])
        for r in rows:
            if r["corrected"] is not None:
                data = r["corrected"]
            elif r["status"] == "auto":
                data = r["record"]
            else:
                data = ""  # pending / not yet reviewed
            w.writerow([r[k] for k in cols] + [data])
        out = io.BytesIO(buf.getvalue().encode())
        out.seek(0)
        return send_file(
            out, mimetype="text/csv", as_attachment=True, download_name="qc_cohort.csv"
        )

    return app


if __name__ == "__main__":
    import os
    import sys

    src, db_path = sys.argv[1], "qc.db"
    if not os.path.exists(db_path):
        build_db(db_path, _load_items(src))
        print(f"built {db_path}")
    create_app(db_path).run(host="0.0.0.0", port=8050)
