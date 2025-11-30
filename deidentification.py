import os
import json
import shutil
import pandas as pd
from datetime import datetime

# ================= 設定區 =================
# 1. 您的原始資料夾路徑 (請修改這裡)
SOURCE_DIR = r"C:\Users\user\Desktop\LLM_Extraction\pathological_report"

# 2. 您想要輸出的新資料夾名稱 (程式會自動建立)
TARGET_DIR = "for_study_deidentified"

# 3. 對照表儲存檔名 (這份檔案包含個資，請妥善保存！)
MAPPING_FILE = "id_mapping_key.csv"

# ================= 主程式 =================
def process_and_anonymize():
    # 如果目標資料夾不存在，則建立
    if not os.path.exists(TARGET_DIR):
        os.makedirs(TARGET_DIR)
        print(f"已建立目標資料夾: {TARGET_DIR}")
    else:
        print(f"目標資料夾已存在: {TARGET_DIR} (新檔案將直接寫入)")

    mapping_list = []
    current_id_num = 1
    
    print(f"開始掃描資料夾: {SOURCE_DIR} ...")

    # os.walk 會遞迴搜尋所有子資料夾
    # root: 目前所在的資料夾路徑
    # dirs: 目前資料夾下的子資料夾清單
    # files: 目前資料夾下的檔案清單
    for root, dirs, files in os.walk(SOURCE_DIR):
        
        # 為了保持順序一致性，建議先排序檔案名稱
        files.sort()
        
        for filename in files:
            # 只處理 JSON 檔
            if not filename.endswith(".json"):
                continue

            # 組合原始完整路徑
            original_path = os.path.join(root, filename)
            
            try:
                # 1. 讀取原始檔案
                with open(original_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 2. 生成新的 Study ID (P001, P002...)
                new_study_id = f"P{current_id_num:03d}"
                new_filename = f"{new_study_id}.json"
                target_path = os.path.join(TARGET_DIR, new_filename)

                # 3. 提取關鍵資訊 (用於對照表)
                # 嘗試抓取病歷號，如果沒有則標示 Unknown
                original_chart_no = data.get("chart_number", "Unknown")
                
                # 4. JSON 內容去識別化 (重要！)
                # 移除病歷號欄位，避免將個資帶入新資料夾
                if "chart_number" in data:
                    del data["chart_number"]
                
                # 加入新的 ID 到 JSON 內容中，方便未來核對
                data["study_id"] = new_study_id

                # 5. 寫入新檔案到 for_study 資料夾
                with open(target_path, 'w', encoding='utf-8') as f_out:
                    json.dump(data, f_out, ensure_ascii=False, indent=4)

                # 6. 記錄到對照表
                mapping_list.append({
                    "Study_ID": new_study_id,       # 新編號 (P001)
                    "Original_Filename": filename,   # 舊檔名 (123456_01.json)
                    "Original_Chart_No": original_chart_no, # 病歷號
                    "Original_Path": original_path   # 原始路徑 (方便回溯)
                })

                print(f"[成功] {filename} -> {new_filename}")
                current_id_num += 1

            except json.JSONDecodeError:
                print(f"[跳過] 無法讀取 JSON: {filename}")
            except Exception as e:
                print(f"[錯誤] 處理 {filename} 時發生錯誤: {e}")

    # ================= 結束作業 =================
    
    # 儲存對照表 CSV
    if mapping_list:
        df_map = pd.DataFrame(mapping_list)
        df_map.to_csv(MAPPING_FILE, index=False, encoding='utf-8-sig')
        
        print("\n" + "="*30)
        print(f"處理完成！共處理 {len(mapping_list)} 份檔案。")
        print(f"1. 去識別化檔案已存於: ./{TARGET_DIR}/")
        print(f"2. 密碼對照表已存於: {MAPPING_FILE} (★請妥善保管此檔★)")
        print("="*30)
    else:
        print("未找到任何 JSON 檔案，請檢查路徑。")

if __name__ == "__main__":
    process_and_anonymize()

### 程式執行後會發生什麼事？

'''
假設您的原始結構是：
pathological_report/
├── P001/
│   └── P001.json  (內含 "chart_number": "P001")
└── 889900/
    └── 889900_01.json  (內含 "chart_number": "889900")

執行後，會產生一個新資料夾 `for_study_deidentified/`：
for_study_deidentified/
├── P001.json  (內容已移除 chart_number，新增 "study_id": "P001")
└── P002.json  (內容已移除 chart_number，新增 "study_id": "P002")
'''