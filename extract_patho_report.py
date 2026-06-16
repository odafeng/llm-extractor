"""
針對 Pathological_Report拷貝 資料夾的病理報告萃取
基於 LLM_assist_batch.py 的結構，TARGET_FOLDERS 指向 Pathological_Report拷貝

LLM 設定：
  - 預設使用地端 Ollama (qwen2.5:14b)
  - 若地端失敗，自動 fallback 到雲端 GPT-5.1（需設定 OPENAI_API_KEY）
  - 環境變數：
      OLLAMA_BASE_URL  (預設 http://localhost:11434/v1)
      OLLAMA_MODEL     (預設 qwen2.5:14b)
      USE_CLOUD_ONLY=1 (強制只用雲端)
"""

import json
import os
import time

import openai
import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

# ================= 0. 環境變數載入 =================
load_dotenv(".env.local")

# ================= 1. API 設定區 =================
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
USE_GPT = True if OPENAI_API_KEY else False
USE_CLOUD_ONLY = os.getenv("USE_CLOUD_ONLY", "0") == "1"

# ================= 2. 路徑設定 =================
TARGET_FOLDERS = ["Pathological_Report拷貝"]
OUTPUT_FILE = "Pathological_Report_Extraction_Result.xlsx"

# ================= 3. Prompt 與 Schema 定義 =================
SYSTEM_PROMPT = """
You are an expert Pathologist Assistant specializing in Rectal Cancer.
Extract clinical data from the pathology report into a strict JSON format.

### EXTRACTION RULES:
1. **Null Handling**: If a value is not mentioned or does not fit the schema options, return `null`.
2. **Unmapped Findings**: If specific findings (e.g., 'High Grade') clearly exist but do not match the allowed options (Well/Moderate/Poor), keep the field null and record the original text in `extraction_notes`.
3. **Unit Standardization**:
   - Tumor size: convert to **cm**.
   - Margins: convert to **mm**.
4. **Conflict Resolution**:
   - Information in 'Synoptic Report' / 'Diagnosis' supersedes 'Gross Description'.
   - 'Addendum' or 'Amended' reports supersede original text.
5. **Lymph Nodes**: If nodes are listed in groups (e.g., perirectal + IMA), **SUM** them for total examined/positive.
6. **Margins (CRITICAL)**:
   - **Distal Margin**: Only extract to `distal_margin_mm` if the text EXPLICITLY says "Distal".
   - **CRM**: Only extract to `CRM_dist_mm` if the text EXPLICITLY says "Circumferential", "Radial", or "CRM".
   - **Ambiguous Margin**: If the text only says "Closest margin", "Distance from resection line", or "Surgical margin" WITHOUT specifying proximal/distal/radial, extract the value to `closest_margin_mm`. **DO NOT GUESS** that it is Distal or CRM.
7. **Tumor Presence**:
   - Set `tumor_found` to `false` ONLY if the report explicitly states "No residual tumor", "No residual carcinoma", or indicates a post-treatment/post-polypectomy status with no cancer cells found (pT0/pTX).
   - In these cases, set `histology`, `grade`, and `tumor_size_cm` to `null`. Do NOT extract histology from the 'History' section.
8. **Tumor Budding (ITBCC 2016 Standard)**:
   - **Bd1_Low**: 0-4 buds. Also map "Not identified", "Absent", "None", or "Negative" to this category.
   - **Bd2_Int**: 5-9 buds.
   - **Bd3_High**: >= 10 buds.
   - If the report explicitly says "High Grade" for budding, map to `Bd3_High`.
9. **EMVI (Extramural Venous Invasion)**: This is SEPARATE from LVI. Do NOT merge them.
   - Map "Extramural venous invasion: Present" to "Positive" (including phrasings like "Present, confirmed by VVG/Desmin stain").
   - Map "Not identified" or "Absent" to "Negative".
   - If the line is an uncleaned template artifact (e.g. "Not identified/Present"), set EMVI to `null` and record the original text in `extraction_notes`.
   - If there is no separate extramural venous field (only a combined "Lymphatic/venous invasion" line), leave EMVI `null`.

### JSON OUTPUT SCHEMA:
{
  "tumor_found": true,            // Boolean. False if 'No residual tumor' / pT0 / pTX.
  "histology": "Adenocarcinoma",  // Null if tumor_found is false
  "grade": "Well",                // Pick one: "Well", "Moderate", "Poor". Null if tumor_found is false
  "pT": "T3",
  "pN": "N1a",
  "nodes_exam": 15,
  "nodes_pos": 1,
  "metastasis": "M0",             // Pick one: "M0", "M1"
  "tumor_size_cm": 3.5,
  "LVI": "Positive",              // Pick one: "Positive", "Negative". Lymphovascular invasion
  "EMVI": "Negative",             // Pick one: "Positive", "Negative". Extramural venous invasion (SEPARATE from LVI)
  "PNI": "Negative",              // Pick one: "Positive", "Negative"
  "Deposits": "Negative",         // Pick one: "Positive", "Negative"
  "Budding": "Low",               // Pick one: "High", "Intermediate", "Low"
  "TME": "Complete",              // Pick one: "Complete", "Incomplete", "Nearly complete"
  "MMR": "pMMR",                  // Pick one: "pMMR", "dMMR"

  "CRM_status": "Negative",       // Pick one: "Positive", "Negative"
  "CRM_dist_mm": 2.0,             // Only if explicitly CRM/Radial
  "distal_margin_mm": 36,         // Only if explicitly Distal

  "closest_margin_mm": 14,        // For ambiguous 'closest margin' / 'resection line'
  "closest_margin_desc": "distance from resection line",

  "extraction_notes": "String. Record unmapped findings (e.g., 'High Grade') or special status (e.g., 'No residual tumor')."
}
"""

# ================= 4. 模型呼叫函式 =================


def _build_messages(text):
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Report:\n{text}\n\nExtract JSON:"},
    ]


def call_local_llm(text):
    client = openai.OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    response = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=_build_messages(text),
        response_format={"type": "json_object"},
        temperature=0,
    )
    return response.choices[0].message.content


def call_gpt5(text):
    if not USE_GPT:
        return None
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-5.1",
        messages=_build_messages(text),
        response_format={"type": "json_object"},
        temperature=0,
    )
    return response.choices[0].message.content


def call_llm(text):
    """先嘗試地端，失敗則 fallback 到雲端。"""
    if not USE_CLOUD_ONLY:
        try:
            return call_local_llm(text), "local"
        except Exception as e:
            print(f"  地端 LLM 失敗: {e}，嘗試雲端 fallback...")
    if USE_GPT:
        try:
            return call_gpt5(text), "cloud"
        except Exception as e:
            print(f"  雲端 GPT 也失敗: {e}")
            return "{}", "error"
    print("  無可用模型（地端失敗且無 OpenAI API Key）")
    return "{}", "error"


# ================= 5. 主程式 =================


def main():
    results_gpt = []
    time_gpt = 0.0

    print("=" * 40)
    if USE_CLOUD_ONLY:
        print("模式：僅雲端")
    else:
        print(f"地端 LLM   : {OLLAMA_MODEL} @ {OLLAMA_BASE_URL}")
    print(f"雲端 fallback: {'[啟用]' if USE_GPT else '[停用 - 未偵測到 Key]'}")
    print("=" * 40)

    if USE_CLOUD_ONLY and not USE_GPT:
        print("錯誤：USE_CLOUD_ONLY=1 但未偵測到 OpenAI API Key。")
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))

    for folder_name in TARGET_FOLDERS:
        folder_path = os.path.join(base_dir, folder_name)

        if not os.path.exists(folder_path):
            print(f"警告：找不到資料夾 {folder_name}，跳過。")
            continue

        print(f"正在處理資料夾：{folder_name}")

        # 取得該資料夾下的所有子資料夾
        chart_dirs = [
            d for d in os.listdir(folder_path) if os.path.isdir(os.path.join(folder_path, d))
        ]
        # 以數字排序
        chart_dirs.sort(key=lambda x: int(x) if x.isdigit() else float("inf"))

        for chart_no in tqdm(chart_dirs, desc=f"Processing {folder_name}"):
            chart_dir_path = os.path.join(folder_path, chart_no)

            json_files = [f for f in os.listdir(chart_dir_path) if f.endswith(".json")]

            row_data = {"Source_Folder": folder_name, "ChartNo": chart_no, "Study_ID": chart_no}

            if not json_files:
                results_gpt.append(row_data)
                continue

            target_json = json_files[0]
            file_path = os.path.join(chart_dir_path, target_json)

            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
                    report_text = data.get("report_text", "")
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                report_text = ""

            if not report_text:
                results_gpt.append(row_data)
                continue

            # 呼叫 LLM（地端優先，fallback 雲端）
            start_time = time.time()
            llm_res, source = call_llm(report_text)
            end_time = time.time()
            time_gpt += end_time - start_time

            try:
                llm_json = json.loads(llm_res)
                row_data.update(llm_json)
            except Exception:
                row_data["Error"] = "ParseFail"
                row_data["Raw_Output"] = llm_res

            row_data["LLM_Source"] = source
            results_gpt.append(row_data)

            # 避免 API Rate Limit
            time.sleep(0.5)

    # ================= 6. 存檔 =================
    if results_gpt:
        cols_order = [
            "Source_Folder",
            "ChartNo",
            "Study_ID",
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
            "LLM_Source",
            "Error",
            "Raw_Output",
        ]

        df_gpt = pd.DataFrame(results_gpt)

        existing_cols = [c for c in cols_order if c in df_gpt.columns]
        remaining_cols = [c for c in df_gpt.columns if c not in cols_order]
        df_gpt = df_gpt[existing_cols + remaining_cols]

        output_path = os.path.join(base_dir, OUTPUT_FILE)
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            df_gpt.to_excel(writer, sheet_name="LLM_Extraction", index=False)

        print(f"\n成功！結果已儲存至: {output_path}")
    else:
        print("沒有產生任何結果。")

    # ================= 7. 輸出耗時統計 =================
    print("\n" + "=" * 40)
    print("模型總耗時統計 (Total Execution Time)")
    print("=" * 40)
    print(f"LLM 總耗時  : {time_gpt:.2f} 秒")
    print(f"報告數量    : {len(results_gpt)} 份")
    print("=" * 40 + "\n")


if __name__ == "__main__":
    main()
