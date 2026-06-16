"""Schema / prompt 一致性測試：防止兩支萃取 pipeline 的 schema 漂移。"""

import re
from pathlib import Path

import pytest

import extract_patho_report as epr
import LLM_assist_batch as lab

# schema 應包含的所有欄位
SCHEMA_FIELDS = [
    "tumor_found",
    "histology",
    "grade",
    "pT",
    "pN",
    "nodes_exam",
    "nodes_pos",
    "metastasis",
    "tumor_size_cm",
    "LVI",
    "EMVI",
    "PNI",
    "Deposits",
    "Budding",
    "TME",
    "MMR",
    "CRM_status",
    "CRM_dist_mm",
    "distal_margin_mm",
    "closest_margin_mm",
    "closest_margin_desc",
    "extraction_notes",
]

REPO_ROOT = Path(__file__).resolve().parent.parent


def _cols_order_block(filename):
    src = (REPO_ROOT / filename).read_text(encoding="utf-8")
    m = re.search(r"cols_order = \[(.*?)\]", src, re.DOTALL)
    assert m, f"找不到 {filename} 的 cols_order"
    return m.group(1)


def test_prompts_are_identical():
    # 兩支萃取 pipeline 必須共用同一份 prompt，避免 schema 漂移
    assert epr.SYSTEM_PROMPT == lab.SYSTEM_PROMPT


@pytest.mark.parametrize("field", SCHEMA_FIELDS)
def test_field_documented_in_prompt(field):
    assert f'"{field}"' in epr.SYSTEM_PROMPT


def test_emvi_rule_present():
    assert "Extramural Venous Invasion" in epr.SYSTEM_PROMPT
    assert "SEPARATE from LVI" in epr.SYSTEM_PROMPT


@pytest.mark.parametrize("filename", ["extract_patho_report.py", "LLM_assist_batch.py"])
@pytest.mark.parametrize("field", SCHEMA_FIELDS)
def test_field_in_output_columns(filename, field):
    # 每個 schema 欄位都必須出現在輸出欄位順序中
    assert f'"{field}"' in _cols_order_block(filename)


def test_build_messages_structure():
    msgs = epr._build_messages("REPORT_BODY_123")
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == epr.SYSTEM_PROMPT
    assert "REPORT_BODY_123" in msgs[1]["content"]
