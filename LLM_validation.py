import os
import json
import pandas as pd
import time
from tqdm import tqdm
import openai
import anthropic
import google.generativeai as genai
from dotenv import load_dotenv

# ================= 0. 環境變數載入 =================
# 載入 .env.local 檔案中的環境變數
load_dotenv('.env.local')

# ================= 1. API 設定區 =================
# 程式會嘗試從環境變數讀取 Key，如果讀不到則會印出警告

# [OpenAI - GPT-5.1]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
USE_GPT = True if OPENAI_API_KEY else False

# [Anthropic - Claude Opus 4.5]
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
USE_CLAUDE = True if ANTHROPIC_API_KEY else False

# [Google - Gemini 3 Pro]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
USE_GEMINI = True if GEMINI_API_KEY else False

# ================= 2. 路徑設定 =================
INPUT_FOLDER = "C:\\Users\\user\\Desktop\\LLM_Extraction\\for_study_deidentified" 
OUTPUT_FILE = "C:\\Users\\user\\Desktop\\LLM_Extraction\\Multi_Model_Extraction_Result.xlsx" 

# ================= 3. Prompt 與 Schema 定義 =================
# 這是給 LLM 的核心指令，包含針對直腸癌的特殊規則
SYSTEM_PROMPT = """
You are an expert Pathologist Assistant specializing in Rectal Cancer. 
Extract clinical data from the pathology report into a strict JSON format.

### EXTRACTION RULES:
1. **Null Handling**: If a value is not mentioned, return `null`.
2. **Unit Standardization**: 
   - Tumor size: convert to **cm**.
   - Margins: convert to **mm**.
3. **Conflict Resolution**: 
   - Information in 'Synoptic Report' / 'Diagnosis' supersedes 'Gross Description'.
   - 'Addendum' or 'Amended' reports supersede original text.
4. **Lymph Nodes**: If nodes are listed in groups (e.g., perirectal + IMA), **SUM** them for total examined/positive.
5. **Margins**: 
   - If 'Closest margin is distal: 36mm', do NOT put 36mm into CRM. CRM must be explicitly circumferential/radial.
6. **Post-Treatment**: If 'No residual tumor' (ypT0), set `tumor_size_cm` to 0.

### JSON OUTPUT SCHEMA:
{
  "histology": "Adenocarcinoma", 
  "grade": "Moderate/Poor/Well",
  "pT": "T3",
  "pN": "N1a",
  "nodes_exam": 15,
  "nodes_pos": 1,
  "metastasis": "M0/M1",
  "tumor_size_cm": 3.5,
  "LVI": "Positive/Negative",
  "PNI": "Positive/Negative",
  "Deposits": "Positive/Negative",
  "Budding": "High/Low/Bd1",
  "CRM_status": "Positive/Negative",
  "CRM_dist_mm": 2.0,
  "Distal_dist_mm": 36,
  "TME": "Complete/Incomplete",
  "MMR": "pMMR/dMMR"
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

def call_claude(text):
    if not USE_CLAUDE: return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        message = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Report:\n{text}\n\nReturn ONLY the JSON object."}]
        )
        return message.content[0].text
    except Exception as e:
        print(f"Claude Error: {e}")
        return "{}"

def call_gemini(text):
    if not USE_GEMINI: return None
    genai.configure(api_key=GEMINI_API_KEY)
    
    # 定義模型名稱
    PRIMARY_MODEL = 'models/gemini-3-pro-preview'
    FALLBACK_MODEL = 'models/gemini-2.5-pro'

    # 共用設定
    gen_config = {"response_mime_type": "application/json", "temperature": 0.1}

    try:
        model = genai.GenerativeModel(PRIMARY_MODEL, generation_config=gen_config)
        response = model.generate_content(SYSTEM_PROMPT + f"\n\nReport:\n{text}")
        return response.text

    except Exception as e1:
        print(f"⚠️ [Gemini 3 Pro] 呼叫失敗: {e1}")
        print(f"🔄 自動切換至 Fallback 模型: {FALLBACK_MODEL} ...")

        try:
            model_fallback = genai.GenerativeModel(FALLBACK_MODEL, generation_config=gen_config)
            response = model_fallback.generate_content(SYSTEM_PROMPT + f"\n\nReport:\n{text}")
            return response.text
            
        except Exception as e2:
            print(f"❌ [Gemini Fallback] 也失敗: {e2}")
            return "{}"

# ================= 5. 主程式 =================

def main():
    files = [f for f in os.listdir(INPUT_FOLDER) if f.endswith('.json')]
    files.sort() # 排序 P001, P002...
    
    # 初始化結果列表
    results_gpt = []
    results_claude = []
    results_gemini = []

    # 初始化計時器 (秒)
    time_gpt = 0.0
    time_claude = 0.0
    time_gemini = 0.0
    
    print(f"準備處理 {len(files)} 份報告...")
    
    # 檢查 Key 是否存在並印出狀態
    print("="*40)
    print(f"GPT-5.1     : {'[啟用]' if USE_GPT else '[停用 - 未偵測到 Key]'}")
    print(f"Claude-4.5 : {'[啟用]' if USE_CLAUDE else '[停用 - 未偵測到 Key]'}")
    print(f"Gemini-3 : {'[啟用]' if USE_GEMINI else '[停用 - 未偵測到 Key]'}")
    print("="*40)

    if not any([USE_GPT, USE_CLAUDE, USE_GEMINI]):
        print("錯誤：沒有偵測到任何 API Key，請檢查您的 .env.local 檔案。")
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

        # 4. 呼叫 Claude
        if USE_CLAUDE:
            start_time = time.time()
            claude_res = call_claude(report_text)
            end_time = time.time()
            time_claude += (end_time - start_time)

            row_data = {"Study_ID": study_id}
            try:
                claude_json = json.loads(claude_res)
                row_data.update(claude_json)
            except:
                row_data["Error"] = "ParseFail"
                row_data["Raw_Output"] = claude_res
            results_claude.append(row_data)

        # 5. 呼叫 Gemini
        if USE_GEMINI:
            start_time = time.time()
            gemini_res = call_gemini(report_text)
            end_time = time.time()
            time_gemini += (end_time - start_time)

            row_data = {"Study_ID": study_id}
            try:
                gemini_json = json.loads(gemini_res)
                row_data.update(gemini_json)
            except:
                row_data["Error"] = "ParseFail"
                row_data["Raw_Output"] = gemini_res
            results_gemini.append(row_data)
        
        # 避免 API Rate Limit (視情況調整)
        time.sleep(0.5)

    # ================= 6. 存檔 =================
    if any([results_gpt, results_claude, results_gemini]):
        with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
            if results_gpt:
                df_gpt = pd.DataFrame(results_gpt)
                df_gpt.to_excel(writer, sheet_name='GPT-5.1', index=False)
            
            if results_claude:
                df_claude = pd.DataFrame(results_claude)
                df_claude.to_excel(writer, sheet_name='Claude-4.5', index=False)
            
            if results_gemini:
                df_gemini = pd.DataFrame(results_gemini)
                df_gemini.to_excel(writer, sheet_name='Gemini-3', index=False)
        
        print(f"\n成功！結果已儲存至: {OUTPUT_FILE}")
    else:
        print("沒有產生任何結果。")

    # ================= 7. 輸出耗時統計 =================
    print("\n" + "="*40)
    print("模型總耗時統計 (Total Execution Time)")
    print("="*40)
    if USE_GPT:
        print(f"GPT-5.1     : {time_gpt:.2f} 秒")
    if USE_CLAUDE:
        print(f"Claude-4.5 : {time_claude:.2f} 秒")
    if USE_GEMINI:
        print(f"Gemini-3 : {time_gemini:.2f} 秒")
    print("="*40 + "\n")

if __name__ == "__main__":
    main()