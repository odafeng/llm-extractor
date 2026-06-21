"""Ensemble QC: run the extractor with several local models and flag fields where they
disagree, then merge with the per-field grounding/rule checks from ``verify`` to produce a
single AUTO-APPROVE / REVIEW verdict per report.

Why: a single model's confidence is poorly calibrated (it can be confidently wrong). Two
independent, gold-free signals catch most real errors — (1) grounding (``verify``: is the
value actually in the report?) and (2) ensemble agreement (do independent models concur?).
Where all models agree *and* nothing is ungrounded, the record can be auto-approved; the
rest is routed to human review.

The consensus/verdict logic is pure (no network) so it is unit-testable; only
``extract_with`` / ``run_ensemble`` touch Ollama.

Config: ENSEMBLE_MODELS (comma-separated Ollama tags; default below).
"""

import json
import os

import verify as V

DEFAULT_MODELS = os.getenv("ENSEMBLE_MODELS", "gemma4:31b,qwen2.5:72b,phi4").split(",")

# fields excluded from cross-model agreement: per-report id and free-text notes
_SKIP = {"file_id", "extraction_notes"}
_DIRECTIONAL = {"distal", "proximal", "circumferential"}


def extract_with(text: str, model: str, base_url: str | None = None) -> dict:
    """Extract one record with a specific Ollama model (reuses the extractor's prompt)."""
    import openai  # lazy: keep the pure consensus logic importable without the SDK

    from extract_patho_report import OLLAMA_BASE_URL, _build_messages

    client = openai.OpenAI(base_url=base_url or OLLAMA_BASE_URL, api_key="ollama")
    resp = client.chat.completions.create(
        model=model,
        messages=_build_messages(text),
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content)


def _norm(value) -> str:
    """Normalise a scalar field value for agreement comparison."""
    if V.is_null(value):
        return ""
    return str(value).strip().lower()


def _involved(value) -> str:
    """Normalise a margin 'involved' flag for agreement comparison."""
    if value in (True, 1, "1", "yes", "true", "True"):
        return "involved"
    if value in (False, 0, "0", "no", "false", "False"):
        return "clear"
    return ""  # unknown / not stated


def _margin_closest(record: dict):
    """Reduce a record's margin list to the clinically decisive (distance, axis, involved).

    ``involved`` is part of the tuple so that two models which agree on the closest
    distance/axis but disagree on whether it is involved (i.e. the positive-vs-negative
    margin decision) are still flagged as disagreeing by ``consensus``.
    """
    cand = []
    for m in record.get("margins") or []:
        if not isinstance(m, dict) or m.get("distance_mm") is None:
            continue
        try:
            dist = float(m["distance_mm"])
        except (TypeError, ValueError):
            continue
        axis = str(m.get("type", "")).strip().lower()
        cand.append(
            (dist, axis if axis in _DIRECTIONAL else "unspecified", _involved(m.get("involved")))
        )
    if not cand:
        return ("", "", "")
    dist, axis, involved = min(cand, key=lambda c: c[0])
    return (round(dist, 1), axis, involved)


def consensus(records: list[dict]) -> dict:
    """Per-field agreement across model records.

    Returns ``{field: {"agree": bool, "values": [...]}}`` over the union of clinical fields.
    Margins are compared by their reduced closest (distance, axis).
    """
    fields: set[str] = set()
    for r in records:
        fields |= {k for k in r if not k.startswith("_") and k not in _SKIP}
    out: dict[str, dict] = {}
    for f in sorted(fields):
        if f == "margins":
            vals = [_margin_closest(r) for r in records]
        else:
            vals = [_norm(r.get(f)) for r in records]
        out[f] = {"agree": len(set(vals)) == 1, "values": vals}
    return out


def ensemble_verdict(
    records: list[dict], text: str, primary: int = 0, review_threshold: float = 0.7
) -> dict:
    """Merge grounding (``verify`` on the primary record) with cross-model agreement into a
    single verdict. No reference standard required."""
    if not records:
        raise ValueError("records must be non-empty")
    rec = records[primary]
    ver = V.verify(rec, text, review_threshold)
    cons = consensus(records)
    disagree = sorted(f for f, d in cons.items() if not d["agree"])
    needs_review = bool(ver["needs_review"] or disagree)
    review_fields = sorted(set(ver["review_fields"]) | set(disagree))
    reasons = list(ver["flags"])
    reasons += [f"{f}: models disagree {cons[f]['values']}" for f in disagree]
    return {
        "record": rec,
        "decision": "REVIEW" if needs_review else "AUTO-APPROVE",
        "needs_review": needs_review,
        "review_fields": review_fields,
        "disagree_fields": disagree,
        "reasons": reasons,
        "overall_confidence": ver["overall_confidence"],
        "consensus": cons,
        "n_models": len(records),
        "models_agree": not disagree,
    }


def run_ensemble(text: str, models: list[str] | None = None, review_threshold: float = 0.7) -> dict:
    """Extract with every model, then return the merged QC verdict (touches Ollama)."""
    models = models or DEFAULT_MODELS
    records = [extract_with(text, m) for m in models]
    out = ensemble_verdict(records, text, review_threshold=review_threshold)
    out["models"] = models
    return out


if __name__ == "__main__":
    import sys

    src = sys.argv[1]
    report = (
        json.loads(open(src).read())["report_text"] if src.endswith(".json") else open(src).read()
    )
    result = run_ensemble(report)
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "consensus"}, ensure_ascii=False, indent=2
        )
    )
