"""End-to-end extraction pipeline: unstructured report in -> structured fields +
per-field confidence + flagged suspicious values out.

    raw report text
        │  extract  (local-first LLM, reuses extract_patho_report.call_llm)
        ▼
    structured JSON
        │  verify   (grounding + schema + clinical rules, no extra LLM call)
        ▼
    {extraction, per-field confidence, flags, needs_review}

CLI:
    python3 pipeline.py report.txt                 # a .txt report
    python3 pipeline.py case.json --key report_text  # a .json with a text field
    cat report.txt | python3 pipeline.py -           # stdin
Add --json to emit machine-readable output instead of the human summary.
"""

from __future__ import annotations

import argparse
import json
import sys

from extract_patho_report import call_llm
from verify import verify


def _parse_json(raw: str) -> dict:
    import re

    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return {}


def run(report_text: str, review_threshold: float = 0.7) -> dict:
    """Extract then verify one report. Returns the full structured result."""
    raw, source = call_llm(report_text)
    record = _parse_json(raw)
    if not record:
        return {
            "source": source,
            "extraction": {},
            "fields": {},
            "overall_confidence": 0.0,
            "flags": ["extraction produced no valid JSON"],
            "needs_review": True,
            "review_fields": [],
        }
    result = verify(record, report_text, review_threshold)
    result["source"] = source
    result["extraction"] = {k: v for k, v in record.items() if not k.startswith("_")}
    return result


def _format(result: dict) -> str:
    lines = []
    flag = "⚠ NEEDS REVIEW" if result["needs_review"] else "✓ clean"
    lines.append(
        f"[{flag}]  overall confidence: {result['overall_confidence']:.2f}"
        f"  (LLM source: {result.get('source', '?')})"
    )
    lines.append("-" * 64)
    lines.append(f"{'field':22s}{'value':28s}{'conf':>6}  flags")
    for f, d in result["fields"].items():
        v = str(d["value"])[:26]
        mark = "" if not d["flags"] else "  ⚠ " + "; ".join(d["flags"])
        lines.append(f"{f:22s}{v:28s}{d['confidence']:>6.2f}{mark}")
    if result["flags"]:
        lines.append("-" * 64)
        lines.append("cross-field flags:")
        lines += [f"  • {m}" for m in result["flags"]]
    if result["review_fields"]:
        lines.append(f"review these fields: {', '.join(result['review_fields'])}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pathology extraction + verification pipeline")
    ap.add_argument("source", help="report .txt, a .json file, or '-' for stdin")
    ap.add_argument("--key", default="report_text", help="text field name for .json input")
    ap.add_argument("--threshold", type=float, default=0.7, help="confidence review threshold")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of human summary")
    args = ap.parse_args(argv)

    if args.source == "-":
        text = sys.stdin.read()
    elif args.source.endswith(".json"):
        with open(args.source, encoding="utf-8") as f:
            text = json.load(f).get(args.key, "")
    else:
        with open(args.source, encoding="utf-8") as f:
            text = f.read()

    result = run(text, args.threshold)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _format(result))


if __name__ == "__main__":
    main()
