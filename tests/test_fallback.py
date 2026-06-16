"""call_llm 的「地端優先 / 雲端 fallback」邏輯測試（不實際呼叫 LLM）。"""

import extract_patho_report as epr


def test_uses_local_when_available(monkeypatch):
    monkeypatch.setattr(epr, "USE_CLOUD_ONLY", False)
    monkeypatch.setattr(epr, "call_local_llm", lambda text: '{"ok": 1}')
    result, source = epr.call_llm("report")
    assert result == '{"ok": 1}'
    assert source == "local"


def test_falls_back_to_cloud_when_local_fails(monkeypatch):
    monkeypatch.setattr(epr, "USE_CLOUD_ONLY", False)
    monkeypatch.setattr(epr, "USE_GPT", True)

    def boom(text):
        raise RuntimeError("local down")

    monkeypatch.setattr(epr, "call_local_llm", boom)
    monkeypatch.setattr(epr, "call_gpt5", lambda text: '{"cloud": 1}')
    result, source = epr.call_llm("report")
    assert result == '{"cloud": 1}'
    assert source == "cloud"


def test_cloud_only_skips_local(monkeypatch):
    monkeypatch.setattr(epr, "USE_CLOUD_ONLY", True)
    monkeypatch.setattr(epr, "USE_GPT", True)

    def boom(text):
        raise AssertionError("USE_CLOUD_ONLY 模式下不應呼叫地端")

    monkeypatch.setattr(epr, "call_local_llm", boom)
    monkeypatch.setattr(epr, "call_gpt5", lambda text: "{}")
    _, source = epr.call_llm("report")
    assert source == "cloud"


def test_returns_error_when_no_model(monkeypatch):
    monkeypatch.setattr(epr, "USE_CLOUD_ONLY", False)
    monkeypatch.setattr(epr, "USE_GPT", False)

    def boom(text):
        raise RuntimeError("local down")

    monkeypatch.setattr(epr, "call_local_llm", boom)
    result, source = epr.call_llm("report")
    assert result == "{}"
    assert source == "error"
