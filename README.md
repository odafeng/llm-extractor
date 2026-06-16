# LLM Pathology Extractor

> 用 LLM 把**非結構化的直腸癌病理報告**萃取成**結構化 JSON / 表格**的 pipeline。
> 支援**地端 (Ollama) 優先、雲端 (GPT / Claude / Gemini) fallback** 的雙軌架構，
> 為「病患資料不能出院」的醫療場景設計。

---

## ⚠️ 重要聲明

- **僅供研究用途**，輸出**不可**直接作為臨床診斷或治療決策依據，所有結果需由病理醫師人工複核。
- 本 repo 內的病理報告（`for_study_deidentified/`）均已**去識別化**（移除病歷號等個資）。
- 含真實病歷號或個資的檔案（對照金鑰、cohort 清單）一律**不進版控**（見 `.gitignore`），請妥善保管於本機。
- 切勿將 API 金鑰寫死在程式碼中，一律使用 `.env.local`（已被 git 忽略）。

---

## 功能特色

- **臨床導向的萃取規則**：針對直腸癌 synoptic report，內建 margin 消歧義（CRM / Distal / closest margin）、淋巴結分組加總、報告區段衝突解決（Synoptic > Gross、Addendum > 原文）、Tumor budding 採 ITBCC 2016 標準。
- **地端 + 雲端雙軌**：預設用地端 Ollama（`qwen2.5:14b`）；失敗時自動 fallback 雲端 GPT。可用 `USE_CLOUD_ONLY=1` 強制只用雲端。
- **多模型橫向比較**：`LLM_validation.py` 可同時跑 GPT-5.1 / Claude / Gemini，輸出到同一份 Excel 的不同分頁，方便比對。
- **隱私 by design**：去識別化與再識別金鑰分離保存。

## 萃取 Schema

每份報告萃取成下列欄位（未提及一律回傳 `null`）：

| 欄位 | 說明 | 允許值 |
|------|------|--------|
| `tumor_found` | 是否有殘餘腫瘤 | `true` / `false` |
| `histology` | 組織型態 | 字串，如 `Adenocarcinoma` |
| `grade` | 分化程度 | `Well` / `Moderate` / `Poor` |
| `pT` / `pN` / `metastasis` | TNM 分期 | 如 `T3` / `N1a` / `M0` |
| `nodes_exam` / `nodes_pos` | 檢出 / 陽性淋巴結數 | 整數（分組會加總） |
| `tumor_size_cm` | 腫瘤大小 | 數值（cm） |
| `LVI` | Lymphovascular invasion | `Positive` / `Negative` |
| `EMVI` | Extramural venous invasion（與 LVI 分開） | `Positive` / `Negative` |
| `PNI` | Perineural invasion | `Positive` / `Negative` |
| `Deposits` | Tumor deposits | `Positive` / `Negative` |
| `Budding` | Tumor budding（ITBCC 2016） | `High` / `Intermediate` / `Low` |
| `TME` | Mesorectum 完整度 | `Complete` / `Nearly complete` / `Incomplete` |
| `MMR` | Mismatch repair status | `pMMR` / `dMMR` |
| `CRM_status` / `CRM_dist_mm` | 環狀切緣狀態 / 距離 | `Positive`/`Negative` / 數值(mm) |
| `distal_margin_mm` | 遠端切緣距離（僅明確標 Distal 時） | 數值(mm) |
| `closest_margin_mm` / `closest_margin_desc` | 未指明方向的最近切緣 | 數值(mm) / 字串 |
| `extraction_notes` | 無法對應或特殊狀況的原文記錄 | 字串 |

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
結構化結果 Excel (.xlsx)
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

複製範本後填入你的金鑰：

```bash
cp .env.local.example .env.local
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
```

## 開發

本專案使用 Ruff（lint + format）、Pyright（type check）、pre-commit 與 GitHub Actions CI。

```bash
pip install ruff pyright pre-commit
pre-commit install          # 啟用 commit 前自動檢查（含 gitleaks 防金鑰外洩）

ruff check .                # lint
ruff format .               # format
pyright                     # type check
```

## 專案結構

```
.
├── deidentification.py          去識別化
├── extract_patho_report.py      萃取（單資料夾，地端+雲端）
├── LLM_assist_batch.py          萃取（多資料夾批次）
├── LLM_validation.py            多模型比較
├── schema.json                  schema 範例
├── for_study_deidentified/      去識別化報告 (JSON)
├── for_study_deidentified_txt/  去識別化報告 (純文字)
├── requirements.txt
├── pyproject.toml               Ruff / Pyright 設定
├── .pre-commit-config.yaml
└── .github/workflows/ci.yml
```
