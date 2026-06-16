# 3. 以 prompt 規則 + 自由格式 JSON 進行萃取

Status: Accepted (2026-06-16)

## Context

要把自由文字的病理報告轉成結構化欄位，當中牽涉 enum 欄位、單位轉換、
報告區段衝突解決、淋巴結分組加總、margin 消歧義等**臨床規則**。
可選方案包括：(a) 在 system prompt 內用自然語言描述規則 + 自由格式 JSON 輸出；
(b) 用嚴格 JSON Schema / function calling 強制結構與 enum。

## Decision

採用 **(a)**：

- 將所有臨床規則寫在 `SYSTEM_PROMPT`，搭配 `response_format={"type": "json_object"}`
  取得自由格式 JSON，`temperature=0` 以求穩定。
- 不採用 strict JSON Schema / function calling 強制 enum。

## Consequences

**正面**
- 規則以自然語言表達，臨床人員可直接讀懂與修改。
- 同一份 prompt 可跨 GPT / Claude / Gemini / 地端 Ollama 通用，利於多模型比較。
- 實作簡單、迭代快。

**負面 / 取捨**
- enum 未被機器強制，模型可能輸出 schema 以外的值而**靜默通過**，
  需後處理驗證（目前尚缺，仰賴人工複核與 `extraction_notes` 記錄）。
- prompt 被複製在多支 script 中，容易漂移；已用「兩支 prompt 必須相同」的
  測試 (`tests/test_schema_consistency.py`) 與共用欄位清單緩解。
- 無 gold standard 自動評分，準確率目前靠人工複核確認。
