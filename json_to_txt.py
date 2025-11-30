import json
import os
from pathlib import Path

def convert_json_to_txt(input_dir, output_dir):
    """
    Converts JSON files in input_dir to TXT files in output_dir.
    Extracts 'report_text' from each JSON file.
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    # Create output directory if it doesn't exist
    output_path.mkdir(parents=True, exist_ok=True)

    files_processed = 0
    
    print(f"Scanning {input_path} for JSON files...")

    for json_file in input_path.glob("*.json"):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            report_text = data.get("report_text", "")
            
            if report_text:
                txt_filename = json_file.stem + ".txt"
                txt_file_path = output_path / txt_filename
                
                with open(txt_file_path, 'w', encoding='utf-8') as f:
                    f.write(report_text)
                
                files_processed += 1
            else:
                print(f"Warning: No 'report_text' found in {json_file.name}")

        except Exception as e:
            print(f"Error processing {json_file.name}: {e}")

    print(f"Conversion complete. Processed {files_processed} files.")
    print(f"TXT files saved to: {output_path.absolute()}")

if __name__ == "__main__":
    INPUT_DIR = "for_study_deidentified"
    OUTPUT_DIR = "for_study_deidentified_txt"
    
    convert_json_to_txt(INPUT_DIR, OUTPUT_DIR)
