"""Verification stage for extracted pathology fields.

Given a structured extraction + the source report text, score per-field confidence
and flag suspicious values. Three signals, NO extra LLM calls:

  1. grounding    — does the extracted value actually appear in the source text?
                    (catches hallucinated numbers / stages that aren't in the report)
  2. schema/enum  — is the value within the allowed set for that field?
  3. clinical rules — cross-field logic consistency (impossible / contradictory combos).

The output drives a human-review queue: fields with low confidence or flags are the
ones a pathologist should check, so reviewers spend effort only where it is risky.
"""

from __future__ import annotations

import re

# ---- allowed enum values (mirrors the SYSTEM_PROMPT schema) ----
ALLOWED = {
    "grade": {"well", "moderate", "poor"},
    "metastasis": {"m0", "m1"},
    "LVI": {"positive", "negative"},
    "EMVI": {"positive", "negative"},
    "PNI": {"positive", "negative"},
    "Deposits": {"positive", "negative"},
    "Budding": {"high", "intermediate", "low"},
    "TME": {"complete", "incomplete", "nearly complete"},
    "MMR": {"pmmr", "dmmr"},
    "CRM_status": {"positive", "negative"},
}

NUMERIC_FIELDS = {
    "nodes_exam",
    "nodes_pos",
    "tumor_size_cm",
    "CRM_dist_mm",
    "distal_margin_mm",
    "closest_margin_mm",
}
CODE_FIELDS = {"pT", "pN", "metastasis"}

# Margin distances must be grounded CONTEXTUALLY: the number has to appear near its
# own margin keyword, not just anywhere in the (long) report. This catches values
# put in the wrong margin bucket or mis-converted (e.g. 1.5 cm read as 150), while a
# legitimately large margin (e.g. a 15 cm proximal margin) still passes because the
# number really does sit next to the keyword. Magnitude is NOT used — a big margin is
# clinically possible.
# Each field maps to (keywords, disqualifiers). closest_margin is the AMBIGUOUS-only
# bucket: the prompt reserves it for a margin given without proximal/distal/radial. So
# its keyword context must be unqualified — a number next to "distal resection line"
# must NOT ground here (it belongs in distal_margin), else a mis-bucketed value escapes
# review. The disqualifiers mirror the prompt's "WITHOUT specifying proximal/distal/
# radial" rule. The other two buckets ARE the qualifier, so they need no exclusion.
NUMERIC_CONTEXT = {
    "CRM_dist_mm": (["circumferential", "radial", "crm"], []),
    "distal_margin_mm": (["distal"], []),
    "closest_margin_mm": (
        ["closest", "nearest margin", "resection line", "surgical margin"],
        ["proximal", "distal", "radial", "circumferential", "crm"],
    ),
}

# concept keywords: if the model asserts a POSITIVE finding the report never
# mentions, that is a hallucination risk worth flagging.
CONCEPT_KEYWORDS = {
    "LVI": ["lymphovascular", "lymphatic", "lymph-vascular", "lvi"],
    "EMVI": ["extramural venous", "emvi", "venous invasion"],
    "PNI": ["perineural", "pni"],
    "Deposits": ["tumor deposit", "deposits"],
    "CRM_status": ["circumferential", "radial margin", "crm"],
}

# OMISSION detection: if the report clearly discusses a concept but the model left the
# field BLANK, that is a likely missed extraction. This was verify's biggest blind spot
# (it only inspected filled fields), and omissions were the majority of its misses.
OMISSION_KEYWORDS = {
    "LVI": ["lymphovascular", "lymph-vascular", "lvi"],
    "PNI": ["perineural", "pni"],
    "Deposits": ["tumor deposit", "tumour deposit"],
    "CRM_status": ["circumferential", "radial margin", "crm"],
    "MMR": ["mismatch repair", "mlh1", "msh2", "msh6", "pms2", "dmmr", "pmmr"],
    "TME": ["mesorect", "intactness of mesorect", "tme"],
    "Budding": ["tumor budding", "tumour budding", "budding"],
}

NULLISH = {"", "null", "none", "n/a", "na", "nan", "not applicable"}


def is_null(v) -> bool:
    if v is None:
        return True
    try:
        import math

        if isinstance(v, float) and math.isnan(v):
            return True
    except Exception:
        pass
    return str(v).strip().lower() in NULLISH


def _text_has_number(value, text: str) -> bool:
    """A number is grounded if it (or its mm<->cm twin) appears in the report."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    cands = {x, x * 10, x / 10}  # cm<->mm
    for c in cands:
        s = f"{c:g}"
        if re.search(rf"(?<!\d){re.escape(s)}(?!\d)", text):
            return True
    return False


def _number_forms(value):
    """The value and its cm<->mm twins, as bare-number strings."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return {f"{c:g}" for c in (x, x * 10, x / 10)}


def _has_number_near(value, text: str, keywords, exclude=(), window: int = 80) -> bool:
    """True if a form of `value` appears within `window` chars of a keyword whose local
    context contains none of the `exclude` disqualifiers."""
    forms = _number_forms(value)
    if not forms:
        return False
    tl = text.lower()
    for kw in keywords:
        start = 0
        while (i := tl.find(kw, start)) >= 0:
            seg = text[max(0, i - window) : i + len(kw) + window]
            segl = seg.lower()
            if not any(x in segl for x in exclude) and any(
                re.search(rf"(?<!\d){re.escape(s)}(?!\d)", seg) for s in forms
            ):
                return True
            start = i + 1
    return False


def _text_has_code(value, text: str) -> bool:
    """pT/pN/M code grounded if the core code (any p/yp prefix) appears."""
    core = re.sub(r"^(yp|p|c)", "", str(value).strip().lower())
    if not core:
        return False
    return re.search(rf"\b(?:yp|p|c)?{re.escape(core)}\b", text, re.IGNORECASE) is not None


def grounding(record: dict, text: str) -> dict:
    """Return {field: True/False/None} — None means 'not a groundable field'."""
    t = text or ""
    out: dict[str, bool | None] = {}
    for f, v in record.items():
        if f.startswith("_") or is_null(v):
            continue
        if f in NUMERIC_CONTEXT:
            kws, excl = NUMERIC_CONTEXT[f]
            out[f] = _has_number_near(v, t, kws, excl)
        elif f in NUMERIC_FIELDS:
            out[f] = _text_has_number(v, t)
        elif f in CODE_FIELDS and f != "metastasis":
            out[f] = _text_has_code(v, t)
        elif f == "metastasis":
            out[f] = re.search(rf"\b(?:yp|p|c)?{re.escape(str(v).lower())}\b", t, re.I) is not None
        elif f == "histology":
            out[f] = "adenocarc" in t.lower() or "carcinoma" in t.lower()
        elif f == "grade":
            stem = {"well": "well", "moderate": "moder", "poor": "poor"}.get(str(v).strip().lower())
            out[f] = (stem in t.lower()) if stem else None
        else:
            out[f] = None
    return out


def schema_flags(record: dict) -> list[tuple[str, str]]:
    flags = []
    for f, allowed in ALLOWED.items():
        v = record.get(f)
        if not is_null(v) and str(v).strip().lower() not in allowed:
            flags.append((f, f"off-schema value {v!r} (allowed: {sorted(allowed)})"))
    return flags


def _stage_num(v):
    m = re.search(r"[tn](\d)", str(v).lower())
    return int(m.group(1)) if m else None


def rule_flags(record: dict) -> list[tuple[str, str]]:
    """Cross-field clinical consistency. Each flag = (field, message)."""
    flags = []
    g = record.get
    ne, npos = g("nodes_exam"), g("nodes_pos")
    if not is_null(ne) and not is_null(npos):
        try:
            if float(npos) > float(ne):
                flags.append(("nodes_pos", f"nodes_pos ({npos}) > nodes_exam ({ne}) — impossible"))
        except ValueError:
            pass
    # pN vs positive-node count
    pn = _stage_num(g("pN")) if not is_null(g("pN")) else None
    if pn is not None and not is_null(npos):
        try:
            if pn == 0 and float(npos) > 0:
                flags.append(("pN", f"pN0 but nodes_pos={npos}"))
            if pn and pn > 0 and float(npos) == 0:
                flags.append(("pN", f"pN{pn} (node-positive) but nodes_pos=0"))
        except ValueError:
            pass
    # no-residual-tumor consistency
    no_tumor = (g("tumor_found") is False) or (_stage_num(g("pT")) == 0)
    if no_tumor:
        for f in ("histology", "grade", "tumor_size_cm"):
            if not is_null(g(f)):
                flags.append((f, f"tumor_found is false / pT0 but {f}={g(f)!r} is set"))
    # CRM status vs distance
    crm = str(g("CRM_status")).strip().lower() if not is_null(g("CRM_status")) else None
    cd = g("CRM_dist_mm")
    if crm == "positive" and not is_null(cd):
        try:
            if float(cd) > 1:
                flags.append(("CRM_dist_mm", f"CRM_status positive but CRM_dist_mm={cd} (>1mm)"))
        except ValueError:
            pass
    return flags


def verify(record: dict, text: str, review_threshold: float = 0.7) -> dict:
    """Score per-field confidence + flags. Returns a structured verification result."""
    ground = grounding(record, text)
    sflags = schema_flags(record)
    rflags = rule_flags(record)
    by_field: dict[str, list[str]] = {}
    for f, msg in sflags + rflags:
        by_field.setdefault(f, []).append(msg)

    tlow = (text or "").lower()
    fields: dict[str, dict] = {}
    for f, v in record.items():
        if f.startswith("_") or is_null(v):
            continue
        conf, flags = 1.0, list(by_field.get(f, []))
        if ground.get(f) is False:
            conf -= 0.5
            flags.append("value not found in source text (possible hallucination)")
        if any(f == sf for sf, _ in sflags):
            conf -= 0.6
        if any(f == rf for rf, _ in rflags):
            conf -= 0.4
        # asserted positive for a concept never mentioned
        if f in CONCEPT_KEYWORDS and str(v).strip().lower() == "positive":
            if not any(k in tlow for k in CONCEPT_KEYWORDS[f]):
                conf -= 0.4
                flags.append("asserts positive but concept not mentioned in report")
        fields[f] = {
            "value": v,
            "confidence": round(max(0.0, min(1.0, conf)), 2),
            "grounded": ground.get(f),
            "flags": flags,
        }

    # omissions: field left blank while the report clearly discusses the concept
    omissions = [
        f
        for f, kws in OMISSION_KEYWORDS.items()
        if is_null(record.get(f)) and any(k in tlow for k in kws)
    ]

    scored = [d["confidence"] for d in fields.values()]
    overall = round(sum(scored) / len(scored), 2) if scored else 1.0
    global_flags = [f"{fld}: {m}" for fld, m in sflags + rflags]
    global_flags += [
        f"{f}: left blank but report discusses the concept (possible omission)" for f in omissions
    ]
    needs_review = (
        overall < review_threshold
        or bool(global_flags)
        or any(d["confidence"] < review_threshold for d in fields.values())
    )
    review_fields = sorted(
        {f for f, d in fields.items() if d["confidence"] < review_threshold or d["flags"]}
        | set(omissions)
    )
    return {
        "fields": fields,
        "overall_confidence": overall,
        "flags": global_flags,
        "needs_review": needs_review,
        "omissions": omissions,
        "review_fields": review_fields,
    }
