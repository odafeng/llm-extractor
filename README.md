# Rectal Cancer Pathology Report Extractor

[![CI](https://github.com/odafeng/llm-extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/odafeng/llm-extractor/actions/workflows/ci.yml)

> 用 LLM 把**非結構化的直腸癌病理報告**萃取成**結構化資料表**的 pipeline。
> 內建臨床導向的萃取規則，並採「**地端 (Ollama) 優先、雲端 (GPT / Claude / Gemini) fallback**」
> 的雙軌架構，為「病患資料不能出院」的醫療場景設計。

---

## 為什麼做這個

把病理報告轉成可分析的結構化欄位（TNM 分期、CRM、TME、MMR、tumor budding…）
傳統上靠人工逐份 chart abstraction，耗時且容易不一致。本專案把這個過程自動化：
餵入報告原文，輸出一列一列、欄位固定的結構化結果，可直接進統計分析或 tumor registry。

難點不在「呼叫 LLM」，而在報告的**自由文字充滿臨床陷阱**——同一個概念有多種寫法、
margin 要分辨 CRM／distal／未指明、淋巴結要跨群組加總、addendum 會推翻原文。
本專案的核心價值就在於把這些規則寫進 prompt（見 [`SYSTEM_PROMPT`](extract_patho_report.py)）。

## ⚠️ 重要聲明

- **僅供研究用途**，輸出**不可**直接作為臨床診斷或治療決策依據，須由病理醫師人工複核。
- 本專案**未經 IRB 審查**，因此**不公開任何病患層級資料**：病理報告、cohort 名冊、對照金鑰等
  一律**不納入版控、僅保留於本機**（見 `.gitignore`）。本 repo 只包含 **pipeline 程式碼與文件**。
- 要實際執行，請於本機自備去識別化報告，放入 `for_study_deidentified/`（此資料夾不隨 repo 發布）。
- 切勿將 API 金鑰寫死在程式碼中，一律使用 `.env.local`（已被 git 忽略，並由 gitleaks 把關）。

## 功能特色

- **臨床導向的萃取規則**：margin 消歧義（CRM / Distal / closest margin）、淋巴結分組加總、
  報告區段衝突解決（Synoptic > Gross、Addendum > 原文）、Tumor budding 採 ITBCC 2016 標準、
  EMVI 與 LVI 分開判讀。
- **地端 + 雲端雙軌**：預設用地端 Ollama（`qwen2.5:14b`）；失敗時自動 fallback 雲端 GPT。
  可用 `USE_CLOUD_ONLY=1` 強制只用雲端。（背景見 [ADR-0001](docs/adr/0001-local-first-llm-with-cloud-fallback.md)）
- **多模型橫向比較**：`LLM_validation.py` 可同時跑 GPT-5.1 / Claude / Gemini，輸出到同一份 Excel 的不同分頁。
- **可信度驗證（verify 階段）**：`verify.py` 在萃取後做三項檢查（不需額外 LLM 呼叫）——
  grounding（萃取值是否真的出現在原文，抓幻覺）、schema/enum 合法性、跨欄位臨床邏輯
  （`nodes_pos>nodes_exam`、pN 與陽性淋巴結數矛盾、pT0／無殘留卻填了 grade…）。
  產出每欄位 **confidence** 與 **needs_review** 旗標，形成人工複核佇列。
- **隱私 by design**：去識別化與再識別金鑰分離保存（見 [ADR-0002](docs/adr/0002-deidentification-with-separated-mapping-key.md)）。

## 範例

輸入（去識別化報告原文片段，示意；實際資料不隨 repo 發布）：

```
1. Histological type: Adenocarcinoma, NOS
2. Histological grade: Moderately differentiated (2 of 4 grade system)
7. Distance of tumor from closest margin: 5 mm (distal cut end)
8. Intactness of mesorectum: Nearly complete
9. Lymphatic(L)/venous(V) invasion: Present(L1/V1)
10 Extramural venous invasion: Not identified
13 Tumor cell budding: Present; 12 buds; High score (10 or more)
17 Lymph nodes, regional(5/16) and IMA(0/1): Metastatic adenocarcinoma (pN2a)
```

輸出（結構化 JSON 的一列）：

```json
{
  "tumor_found": true,
  "histology": "Adenocarcinoma",
  "grade": "Moderate",
  "pT": "T1",
  "pN": "N2a",
  "nodes_exam": 17,
  "nodes_pos": 5,
  "tumor_size_cm": 0.6,
  "LVI": "Positive",
  "EMVI": "Negative",
  "Budding": "High",
  "TME": "Nearly complete",
  "MMR": "pMMR",
  "CRM_status": "Negative",
  "closest_margin_mm": 5,
  "closest_margin_desc": "distal cut end"
}
```

注意：淋巴結 `regional(5/16)` + `IMA(0/1)` 被**加總**成 17 檢出 / 5 陽性；
「closest margin 5 mm」未指明是 CRM 還是 distal，因此落在 `closest_margin_mm` 而非猜測。

## 萃取 Schema（直腸癌 synoptic）

Schema 對齊國際病理報告標準：**AJCC 8th edition**（TNM 分期）、**CAP** colorectal synoptic
protocol（欄位定義）、**ITBCC 2016**（tumor budding 分級）。欄位依臨床意義分組，
未提及一律回傳 `null`。標 🔶 者為**直腸癌特異**（相對於一般大腸癌）的局部復發 / 預後關鍵指標。

**腫瘤與分期**

| 欄位 | 說明 | 允許值 |
|------|------|--------|
| `tumor_found` | 是否有殘餘腫瘤（治療後 / pT0 為 `false`） | `true` / `false` |
| `histology` | 組織型態 | 字串，如 `Adenocarcinoma` |
| `grade` | 分化程度 | `Well` / `Moderate` / `Poor` |
| `pT` / `pN` / `metastasis` | TNM 分期（AJCC 8th） | 如 `T3` / `N1a` / `M0` |
| `nodes_exam` / `nodes_pos` | 檢出 / 陽性淋巴結數（跨群組**自動加總**） | 整數 |
| `tumor_size_cm` | 腫瘤大小 | 數值（cm） |

**侵犯與沉積（預後因子）**

| 欄位 | 說明 | 允許值 |
|------|------|--------|
| `LVI` | Lymphovascular invasion | `Positive` / `Negative` |
| `EMVI` 🔶 | Extramural venous invasion —— 直腸癌獨立預後因子，**與 LVI 分開判讀** | `Positive` / `Negative` |
| `PNI` | Perineural invasion | `Positive` / `Negative` |
| `Deposits` | Tumor deposits | `Positive` / `Negative` |
| `Budding` | Tumor budding（ITBCC 2016 標準） | `High` / `Intermediate` / `Low` |

**切緣 Margin（直腸癌局部復發關鍵）**

| 欄位 | 說明 | 允許值 |
|------|------|--------|
| `CRM_status` / `CRM_dist_mm` 🔶 | Circumferential resection margin 狀態 / 距離 | `Positive`/`Negative` / 數值(mm) |
| `distal_margin_mm` | 遠端切緣距離（僅文字明確標 *Distal* 時） | 數值(mm) |
| `closest_margin_mm` / `closest_margin_desc` | 未指明方向的最近切緣（**不臆測**為 CRM/distal） | 數值(mm) / 字串 |

**結構完整度 / 分子 / 註記**

| 欄位 | 說明 | 允許值 |
|------|------|--------|
| `TME` 🔶 | 全直腸繫膜切除（mesorectum）完整度 —— 直腸特異 | `Complete` / `Nearly complete` / `Incomplete` |
| `MMR` | Mismatch repair status | `pMMR` / `dMMR` |
| `extraction_notes` | 無法對應或特殊狀況的原文記錄 | 字串 |

> **為什麼是這些欄位**：它們是直腸癌 synoptic report 的核心分期與預後變數。其中
> **CRM、TME、EMVI**（🔶）是直腸癌相對於一般大腸癌特別重要的局部復發 / 預後指標 ——
> 也正是傳統結構化資料庫最常缺漏、卻最有研究價值的欄位。

正式欄位定義（含每個欄位的型別、允許值與臨床說明）見 [`schema.schema.json`](schema.schema.json)（JSON Schema）；
一筆範例輸出見 [`schema.json`](schema.json)；設計取捨見 [ADR-0003](docs/adr/0003-prompt-based-extraction-with-freeform-json.md)。

## Pipeline 架構

```
原始報告 JSON (含病歷號)
   │
   ├─ deidentification.py   → 去識別化：移除病歷號、改 Pxxx 流水號
   │                          （再識別金鑰 id_mapping_key.csv 另存本機）
   ▼
for_study_deidentified/*.json   (去識別化後的報告)
   │
   ▼
萃取 (擇一)：
   ├─ extract_patho_report.py   單一資料夾，地端優先 + 雲端 fallback
   ├─ LLM_assist_batch.py       多資料夾批次，地端優先 + 雲端 fallback
   └─ LLM_validation.py         多模型 (GPT/Claude/Gemini) 橫向比較
   │
   ▼
verify.py   驗證：grounding + schema/enum + 臨床規則 → 每欄 confidence + 旗標
   │
   ▼
結構化結果 Excel (.xlsx)   含 overall_confidence / needs_review / review_fields / flags，
                          需複核的列自動排到最前面
```

單份報告也可即時跑「萃取 + 驗證」一條龍（`pipeline.py`）：

```
報告原文 ──▶ pipeline.py ──▶ {結構化欄位, 每欄 confidence, needs_review, flags}
```

## 安裝

需求：Python 3.11+。

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

地端推論需另外安裝 [Ollama](https://ollama.com/) 並拉取模型：

```bash
ollama pull qwen2.5:14b
```

## 環境變數設定

```bash
cp .env.local.example .env.local   # 再填入你的金鑰
```

`.env.local`（已被 git 忽略，**切勿 commit**）：

| 變數 | 用途 | 預設 |
|------|------|------|
| `OPENAI_API_KEY` | 雲端 GPT / fallback | （無） |
| `ANTHROPIC_API_KEY` | Claude（多模型比較用） | （無） |
| `GEMINI_API_KEY` | Gemini（多模型比較用） | （無） |
| `OLLAMA_BASE_URL` | 地端 Ollama 位址 | `http://localhost:11434/v1` |
| `OLLAMA_MODEL` | 地端模型名稱 | `qwen2.5:14b` |
| `USE_CLOUD_ONLY` | 設 `1` 則強制只用雲端 | `0` |

## 使用方式

```bash
# 去識別化（先改腳本內 SOURCE_DIR 指向你的原始資料夾）
python deidentification.py

# 萃取（地端優先，地端失敗自動轉雲端）
python extract_patho_report.py

# 多資料夾批次萃取
python LLM_assist_batch.py

# 多模型橫向比較（需設定對應的 API 金鑰）
python LLM_validation.py

# 單份報告：萃取 + 驗證一條龍（輸出欄位 + 信心分數 + 可疑標記）
python pipeline.py case.json --key report_text   # .json
python pipeline.py report.txt                     # 純文字
cat report.txt | python pipeline.py -             # stdin
python pipeline.py case.json --json               # 機器可讀輸出
```

`extract_patho_report.py` 整批跑完，輸出的 Excel 會多出 `overall_confidence`、
`needs_review`、`review_fields`、`flags` 四欄，且需複核的列已排到最前面，可直接當複核佇列。

## 開發

本專案使用 Ruff（lint + format）、Pyright（type check）、pytest、pre-commit 與 GitHub Actions CI。

```bash
pip install ruff pyright pytest pre-commit
pre-commit install          # 啟用 commit 前自動檢查（含 gitleaks 防金鑰外洩）

ruff check .                # lint
ruff format .               # format
pyright                     # type check
pytest                      # 測試（schema 一致性 + fallback 邏輯）
```

CI（`.github/workflows/ci.yml`）含三個 job：`lint-and-typecheck`、`test`、`secret-scan`。

## 限制與已知問題

- **enum 仍非生成時強制**：採自由格式 JSON，模型生成當下不受 schema 約束；但 `verify.py`
  會在事後標出 off-schema 值與低信心欄位，把「靜默通過」變成「進複核佇列」。
- **verify 是啟發式、非保證**：grounding／規則能抓「幻覺、矛盾、off-schema」，但無法保證抓出
  所有錯誤（例如原文有、模型抄錯成另一個合法值，grounding 仍會通過）。仍需人工複核高風險欄位。
- **無 gold standard 自動評分**：目前準確率靠人工比對，尚無自動化 per-field accuracy。
- **文字級去識別化未做**：僅移除結構化病歷號，報告自由文字內若殘留姓名／日期未必清除。
- **雲端 fallback 是隱性的**：地端故障時 PHI 會送往雲端，正式使用前應加上明確政策與紀錄。

## 專案結構

```
.
├── deidentification.py          去識別化
├── extract_patho_report.py      萃取（單資料夾，地端+雲端）
├── LLM_assist_batch.py          萃取（多資料夾批次）
├── LLM_validation.py            多模型比較
├── verify.py                    驗證階段（grounding + schema + 臨床規則 → 信心分數/旗標）
├── pipeline.py                  單份報告：萃取 + 驗證一條龍 (CLI)
├── schema.schema.json           正式欄位定義 (JSON Schema，含臨床說明)
├── schema.json                  一筆範例輸出
├── for_study_deidentified/      去識別化報告 (JSON)　← 本機資料，未隨 repo 發布
├── for_study_deidentified_txt/  去識別化報告 (純文字)　← 本機資料，未隨 repo 發布
├── tests/                       schema 一致性 + fallback 測試
├── docs/adr/                    架構決策記錄 (ADR)
├── requirements.txt
├── pyproject.toml               Ruff / Pyright / pytest 設定
├── .pre-commit-config.yaml
├── .gitleaks.toml
└── .github/workflows/ci.yml
```
