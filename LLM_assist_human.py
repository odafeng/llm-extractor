import os
import json
import pandas as pd
import time
from tqdm import tqdm
import openai
from dotenv import load_dotenv

# ================= 0. 環境變數載入 =================
# 載入 .env.local 檔案中的環境變數
load_dotenv('.env.local')

# ================= 1. API 設定區 =================
# 程式會嘗試從環境變數讀取 Key，如果讀不到則會印出警告

# [OpenAI - GPT-5.1]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
USE_GPT = True if OPENAI_API_KEY else False

# ================= 2. 路徑設定 =================
INPUT_FOLDER = "C:\\Users\\user\\Desktop\\LLM_Extraction\\for_study_deidentified" 
OUTPUT_FILE = "C:\\Users\\user\\Desktop\\LLM_Extraction\\Multi_Model_Extraction_Result.xlsx" 

# ================= 3. Prompt 與 Schema 定義 =================
# 這是給 LLM 的核心指令，包含針對直腸癌的特殊規則

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

### JSON OUTPUT SCHEMA:
{
  "tumor_found": true,            // Boolean. False if 'No residual tumor' / pT0 / pTX.
  "histology": "Adenocarcinoma",  // Null if tumor_found is false
  "grade": "Moderate/Poor/Well",  // Null if tumor_found is false
  "pT": "T3",
  "pN": "N1a",
  "nodes_exam": 15,
  "nodes_pos": 1,
  "metastasis": "M0/M1",
  "tumor_size_cm": 3.5,
  "LVI": "Positive/Negative",
  "PNI": "Positive/Negative",
  "Deposits": "Positive/Negative",
  "Budding": "High/Intermediate/Low",
  "TME": "Complete/Incomplete/Nearly complete",
  "MMR": "pMMR/dMMR",

  "CRM_status": "Positive/Negative",
  "CRM_dist_mm": 2.0,             // Only if explicitly CRM/Radial
  "distal_margin_mm": 36,         // Only if explicitly Distal
  
  "closest_margin_mm": 14,        // For ambiguous 'closest margin' / 'resection line'
  "closest_margin_desc": "distance from resection line", 

  "extraction_notes": "String. Record unmapped findings (e.g., 'High Grade') or special status (e.g., 'No residual tumor')."
}
"""

# ================= 4. 模型呼叫函式 =================

def call_gpt5(text):
    if not USE_GPT: return None
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    try:
        response = client.chat.completions.create(
            model="gpt-5.1",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Report:\n{text}\n\nExtract JSON:"}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"GPT Error: {e}")
        return "{}"

# ================= 5. 主程式 =================

def main():
    files = [f for f in os.listdir(INPUT_FOLDER) if f.endswith('.json')]
    files.sort() # 排序 P001, P002...
    
    # 初始化結果列表
    results_gpt = []

    # 初始化計時器 (秒)
    time_gpt = 0.0
    
    print(f"準備處理 {len(files)} 份報告...")
    
    # 檢查 Key 是否存在並印出狀態
    print("="*40)
    print(f"GPT-5.1     : {'[啟用]' if USE_GPT else '[停用 - 未偵測到 Key]'}")
    print("="*40)

    if not USE_GPT:
        print("錯誤：沒有偵測到 OpenAI API Key，請檢查您的 .env.local 檔案。")
        return

    for filename in tqdm(files):
        file_path = os.path.join(INPUT_FOLDER, filename)
        study_id = filename.replace(".json", "")
        
        # 1. 讀取內文
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 根據您的檔案結構，內文直接在 'report_text'
            report_text = data.get("report_text", "")

        if not report_text:
            continue

        # 3. 呼叫 GPT
        if USE_GPT:
            start_time = time.time()
            gpt_res = call_gpt5(report_text)
            end_time = time.time()
            time_gpt += (end_time - start_time)

            row_data = {"Study_ID": study_id}
            try:
                gpt_json = json.loads(gpt_res)
                row_data.update(gpt_json)
            except:
                row_data["Error"] = "ParseFail"
                row_data["Raw_Output"] = gpt_res
            results_gpt.append(row_data)
        
        # 避免 API Rate Limit (視情況調整)
        time.sleep(0.5)

    # ================= 6. 存檔 =================
    if results_gpt:
        with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
            df_gpt = pd.DataFrame(results_gpt)
            df_gpt.to_excel(writer, sheet_name='GPT-5.1', index=False)
        
        print(f"\n成功！結果已儲存至: {OUTPUT_FILE}")
    else:
        print("沒有產生任何結果。")

    # ================= 7. 輸出耗時統計 =================
    print("\n" + "="*40)
    print("模型總耗時統計 (Total Execution Time)")
    print("="*40)
    if USE_GPT:
        print(f"GPT-5.1     : {time_gpt:.2f} 秒")
    print("="*40 + "\n")

if __name__ == "__main__":
    main()