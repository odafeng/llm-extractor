import os
import json
import pandas as pd
from collections import Counter

# ================= 設定區 =================
# 您的資料夾根目錄
ROOT_DIR = r"C:\Users\user\Desktop\LLM_Extraction\pathological_report" 

# 假設您的 JSON 結構中，病理報告內文的 Key 是什麼？
# 根據上一段對話，可能是 "report_text" -> "full_text" 或直接是 "report_text"
# 請根據實際 JSON 修改這裡
def get_text_from_json(json_data):
    # 先嘗試取出 report_text
    content = json_data.get("report_text", "")
    
    # 情況 A: 如果取出來直接是字串 (您的檔案是這種)
    if isinstance(content, str):
        return content
        
    # 情況 B: 如果取出來是字典 (為了預防萬一您有舊格式)
    elif isinstance(content, dict):
        return content.get("full_text", "")
        
    # 情況 C: 什麼都沒有
    return ""

# ================= 關鍵字定義 =================
# 轉成小寫比對
# 1. 手術術式 (出現這些通常就是 Level VI)
RESECTION_KEYWORDS = [
    "low anterior resection", "lar",
    "abdominoperineal resection", "apr",
    "anterior resection", "ar",
    "sigmoidectomy", "colectomy", "hemicolectomy",
    "hartmann", "miles", "intersphincteric resection", "isr"
]

# 2. 只有根治手術才有的特徵 (Biopsy 不會有淋巴結計數)
FEATURE_KEYWORDS = [
    "lymph nodes", "regional lymph nodes", 
    "circumferential resection margin", "crm",
    "mesorectum", "mesorectal"
]

# 3. 排除關鍵字 (如果只出現這些，通常不是我們要的)
EXCLUSION_KEYWORDS = [
    "biopsy", "polypectomy", "mucospctomy", "cytology"
]

# ================= 主程式 =================
def classify_report(text):
    text_lower = text.lower()
    
    # 權重計分
    score = 0
    reasons = []

    # 檢查術式
    for kw in RESECTION_KEYWORDS:
        if kw in text_lower:
            score += 5
            reasons.append(f"Surgery({kw})")
            break # 找到一個術式就夠了

    # 檢查特徵 (淋巴結是關鍵)
    # 簡單檢查：有沒有 "x/y" 這種淋巴結格式，或是文字提到 lymph nodes
    if "lymph node" in text_lower:
        score += 3
        reasons.append("Feature(LymphNode)")
    
import os
import json
import pandas as pd
from collections import Counter

# ================= 設定區 =================
# 您的資料夾根目錄
ROOT_DIR = r"C:\Users\user\Desktop\LLM_Extraction\pathological_report" 

# 假設您的 JSON 結構中，病理報告內文的 Key 是什麼？
# 根據上一段對話，可能是 "report_text" -> "full_text" 或直接是 "report_text"
# 請根據實際 JSON 修改這裡
def get_text_from_json(json_data):
    # 先嘗試取出 report_text
    content = json_data.get("report_text", "")
    
    # 情況 A: 如果取出來直接是字串 (您的檔案是這種)
    if isinstance(content, str):
        return content
        
    # 情況 B: 如果取出來是字典 (為了預防萬一您有舊格式)
    elif isinstance(content, dict):
        return content.get("full_text", "")
        
    # 情況 C: 什麼都沒有
    return ""

# ================= 關鍵字定義 =================
# 轉成小寫比對
# 1. 手術術式 (出現這些通常就是 Level VI)
RESECTION_KEYWORDS = [
    "low anterior resection", "lar",
    "abdominoperineal resection", "apr",
    "anterior resection", "ar",
    "sigmoidectomy", "colectomy", "hemicolectomy",
    "hartmann", "miles", "intersphincteric resection", "isr"
]

# 2. 只有根治手術才有的特徵 (Biopsy 不會有淋巴結計數)
FEATURE_KEYWORDS = [
    "lymph nodes", "regional lymph nodes", 
    "circumferential resection margin", "crm",
    "mesorectum", "mesorectal"
]

# 3. 排除關鍵字 (如果只出現這些，通常不是我們要的)
EXCLUSION_KEYWORDS = [
    "biopsy", "polypectomy", "mucospctomy", "cytology"
]

# ================= 主程式 =================
def classify_report(text):
    text_lower = text.lower()
    
    # 權重計分
    score = 0
    reasons = []

    # 檢查術式
    for kw in RESECTION_KEYWORDS:
        if kw in text_lower:
            score += 5
            reasons.append(f"Surgery({kw})")
            break # 找到一個術式就夠了

    # 檢查特徵 (淋巴結是關鍵)
    # 簡單檢查：有沒有 "x/y" 這種淋巴結格式，或是文字提到 lymph nodes
    if "lymph node" in text_lower:
        score += 3
        reasons.append("Feature(LymphNode)")
    
    if "circumferential" in text_lower or "mesorectum" in text_lower:
        score += 2
        reasons.append("Feature(CRM/TME)")

    # 檢查是否單純 Biopsy
    # 注意：Resection 報告裡也會提到 "Previous biopsy"，所以不能看到 biopsy 就刪
    if any(ex in text_lower for ex in EXCLUSION_KEYWORDS):
        if score < 3: # 分數低且有 biopsy 字眼
            score -= 5
            reasons.append("Exclude(Biopsy_Only)")

    # 最終判定
    if score >= 3:
        return "KEEP", ", ".join(reasons)
    elif score <= 0:
        return "DROP", ", ".join(reasons)
    else:
        return "UNSURE", ", ".join(reasons)

def main():
    results = []
    
    print(f"開始掃描資料夾: {ROOT_DIR} ...")
    
    file_count = 0
    json_count = 0
    
    for root, dirs, files in os.walk(ROOT_DIR):
        for file in files:
            file_count += 1
            if not file.endswith(".json"):
                continue
            
            json_count += 1
            file_path = os.path.join(root, file)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 取得內文
                report_text = get_text_from_json(data)
                
                # 取得 ID (假設檔名是 ID 或 JSON 內有 ID)
                file_id = os.path.splitext(file)[0]
                
                if not report_text:
                    results.append({
                        "File": file,
                        "Path": file_path,
                        "Status": "ERROR",
                        "Reason": "No Text Found",
                        "Text_Snippet": ""
                    })
                    continue

                # 判斷
                status, reason = classify_report(report_text)
                
                results.append({
                    "File": file_id,
                    "Path": file_path,
                    "Status": status,
                    "Reason": reason,
                    "Text_Snippet": report_text[:100].replace("\n", " ") # 預覽前100字
                })
                
            except Exception as e:
                print(f"Error reading {file}: {e}")

    print(f"掃描結束。共發現 {file_count} 個檔案，其中 {json_count} 個是 JSON 檔。")

    if not results:
        print("錯誤：沒有產生任何結果。請檢查資料夾路徑或檔案格式。")
        return

    # 轉成 DataFrame
    df = pd.DataFrame(results)
    
    if 'Status' not in df.columns:
        print("錯誤：結果中沒有 'Status' 欄位。")
        print(df.head())
        return

    # 統計結果
    print("\n分類統計：")
    print(df['Status'].value_counts())
    
    # 顯示被 DROP 的項目
    dropped_df = df[df['Status'] == 'DROP']
    if not dropped_df.empty:
        print(f"\n以下 {len(dropped_df)} 個報告被標記為 DROP (將被排除):")
FEATURE_KEYWORDS = [
    "lymph nodes", "regional lymph nodes", 
    "circumferential resection margin", "crm",
    "mesorectum", "mesorectal"
]

# 3. 排除關鍵字 (如果只出現這些，通常不是我們要的)
EXCLUSION_KEYWORDS = [
    "biopsy", "polypectomy", "mucospctomy", "cytology"
]

# ================= 主程式 =================
def classify_report(text):
    text_lower = text.lower()
    
    # 權重計分
    score = 0
    reasons = []

    # 檢查術式
    for kw in RESECTION_KEYWORDS:
        if kw in text_lower:
            score += 5
            reasons.append(f"Surgery({kw})")
            break # 找到一個術式就夠了

    # 檢查特徵 (淋巴結是關鍵)
    # 簡單檢查：有沒有 "x/y" 這種淋巴結格式，或是文字提到 lymph nodes
    if "lymph node" in text_lower:
        score += 3
        reasons.append("Feature(LymphNode)")
    
import os
import json
import pandas as pd
from collections import Counter

# ================= 設定區 =================
# 您的資料夾根目錄
ROOT_DIR = r"C:\Users\user\Desktop\LLM_Extraction\pathological_report" 

# 假設您的 JSON 結構中，病理報告內文的 Key 是什麼？
# 根據上一段對話，可能是 "report_text" -> "full_text" 或直接是 "report_text"
# 請根據實際 JSON 修改這裡
def get_text_from_json(json_data):
    # 先嘗試取出 report_text
    content = json_data.get("report_text", "")
    
    # 情況 A: 如果取出來直接是字串 (您的檔案是這種)
    if isinstance(content, str):
        return content
        
    # 情況 B: 如果取出來是字典 (為了預防萬一您有舊格式)
    elif isinstance(content, dict):
        return content.get("full_text", "")
        
    # 情況 C: 什麼都沒有
    return ""

# ================= 關鍵字定義 =================
# 轉成小寫比對
# 1. 手術術式 (出現這些通常就是 Level VI)
RESECTION_KEYWORDS = [
    "low anterior resection", "lar",
    "abdominoperineal resection", "apr",
    "anterior resection", "ar",
    "sigmoidectomy", "colectomy", "hemicolectomy",
    "hartmann", "miles", "intersphincteric resection", "isr"
]

# 2. 只有根治手術才有的特徵 (Biopsy 不會有淋巴結計數)
FEATURE_KEYWORDS = [
    "lymph nodes", "regional lymph nodes", 
    "circumferential resection margin", "crm",
    "mesorectum", "mesorectal"
]

# 3. 排除關鍵字 (如果只出現這些，通常不是我們要的)
EXCLUSION_KEYWORDS = [
    "biopsy", "polypectomy", "mucospctomy", "cytology"
]

# ================= 主程式 =================
def classify_report(text):
    text_lower = text.lower()
    
    # 權重計分
    score = 0
    reasons = []

    # 檢查術式
    for kw in RESECTION_KEYWORDS:
        if kw in text_lower:
            score += 5
            reasons.append(f"Surgery({kw})")
            break # 找到一個術式就夠了

    # 檢查特徵 (淋巴結是關鍵)
    # 簡單檢查：有沒有 "x/y" 這種淋巴結格式，或是文字提到 lymph nodes
    if "lymph node" in text_lower:
        score += 3
        reasons.append("Feature(LymphNode)")
    
    if "circumferential" in text_lower or "mesorectum" in text_lower:
        score += 2
        reasons.append("Feature(CRM/TME)")

    # 檢查是否單純 Biopsy
    # 注意：Resection 報告裡也會提到 "Previous biopsy"，所以不能看到 biopsy 就刪
    if any(ex in text_lower for ex in EXCLUSION_KEYWORDS):
        if score < 3: # 分數低且有 biopsy 字眼
            score -= 5
            reasons.append("Exclude(Biopsy_Only)")

    # 最終判定
    if score >= 3:
        return "KEEP", ", ".join(reasons)
    elif score <= 0:
        return "DROP", ", ".join(reasons)
    else:
        return "UNSURE", ", ".join(reasons)

def main():
    results = []
    
    print(f"開始掃描資料夾: {ROOT_DIR} ...")
    
    file_count = 0
    json_count = 0
    
    for root, dirs, files in os.walk(ROOT_DIR):
        for file in files:
            file_count += 1
            if not file.endswith(".json"):
                continue
            
            json_count += 1
            file_path = os.path.join(root, file)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 取得內文
                report_text = get_text_from_json(data)
                
                # 取得 ID (假設檔名是 ID 或 JSON 內有 ID)
                file_id = os.path.splitext(file)[0]
                
                if not report_text:
                    results.append({
                        "File": file,
                        "Path": file_path,
                        "Status": "ERROR",
                        "Reason": "No Text Found",
                        "Text_Snippet": ""
                    })
                    continue

                # 判斷
                status, reason = classify_report(report_text)
                
                results.append({
                    "File": file_id,
                    "Path": file_path,
                    "Status": status,
                    "Reason": reason,
                    "Text_Snippet": report_text[:100].replace("\n", " ") # 預覽前100字
                })
                
            except Exception as e:
                print(f"Error reading {file}: {e}")

    print(f"掃描結束。共發現 {file_count} 個檔案，其中 {json_count} 個是 JSON 檔。")

    if not results:
        print("錯誤：沒有產生任何結果。請檢查資料夾路徑或檔案格式。")
        return

    # 轉成 DataFrame
    df = pd.DataFrame(results)
    
    if 'Status' not in df.columns:
        print("錯誤：結果中沒有 'Status' 欄位。")
        print(df.head())
        return

    # 統計結果
    print("\n分類統計：")
    print(df['Status'].value_counts())
    
    # 顯示被 DROP 的項目
    dropped_df = df[df['Status'] == 'DROP']
    if not dropped_df.empty:
        print(f"\n以下 {len(dropped_df)} 個報告被標記為 DROP (將被排除):")
        for index, row in dropped_df.iterrows():
            print(f"- {row['File']}: {row['Reason']}")
    else:
        print("\n沒有報告被標記為 DROP。")

    # 存檔供檢查
    output_csv = "report_classification_check.csv"
    try:
        df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"\n詳細清單已儲存至: {output_csv}")
        print("請打開 CSV 檢查 'UNSURE' 和 'DROP' 的項目是否正確。")
    except PermissionError:
        print(f"\n錯誤：無法寫入 {output_csv}。請檢查檔案是否已被開啟 (例如在 Excel 中)。")
    except Exception as e:
        print(f"\n儲存 CSV 時發生錯誤: {e}")

if __name__ == "__main__":
    main()