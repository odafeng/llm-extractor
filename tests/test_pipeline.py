"""Tests for the end-to-end pipeline (LLM call is monkeypatched — no network)."""

import json

import pipeline as P


def test_run_assembles_extraction_and_verification(monkeypatch):
    fake = json.dumps({"pT": "T3", "nodes_exam": 15, "nodes_pos": 3})
    monkeypatch.setattr(P, "call_llm", lambda text: (fake, "local"))
    out = P.run("Adenocarcinoma pT3, 3 of 15 nodes positive.")
    assert out["source"] == "local"
    assert out["extraction"]["pT"] == "T3"
    assert "overall_confidence" in out and "fields" in out
    assert out["fields"]["pT"]["grounded"] is True


def test_run_handles_json_in_code_fence(monkeypatch):
    fenced = '```json\n{"pT": "T2"}\n```'
    monkeypatch.setattr(P, "call_llm", lambda text: (fenced, "local"))
    out = P.run("pT2 tumor")
    assert out["extraction"]["pT"] == "T2"


def test_run_flags_unparseable_output(monkeypatch):
    monkeypatch.setattr(P, "call_llm", lambda text: ("not json at all", "error"))
    out = P.run("whatever")
    assert out["needs_review"] is True
    assert out["overall_confidence"] == 0.0
    assert out["extraction"] == {}


def test_internal_keys_stripped_from_extraction(monkeypatch):
    fake = json.dumps({"pT": "T1", "_status": "ok"})
    monkeypatch.setattr(P, "call_llm", lambda text: (fake, "local"))
    out = P.run("pT1")
    assert "_status" not in out["extraction"]
