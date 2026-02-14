
import os
import json
import re
from datetime import datetime

def run_auto_repair():
    today_str = datetime.now().strftime('%Y-%m-%d')
    reports_dir = "memory/sandman/reports"
    integrity_report_path = os.path.join(reports_dir, f"integrity-{today_str}.json")
    repair_report_path = os.path.join(reports_dir, f"repairs-{today_str}.json")

    repairs_report = {
        "timestamp": datetime.now().isoformat(),
        "repairs_attempted": 0,
        "repairs_successful": 0,
        "unfixable_issues": [],
        "details": []
    }

    integrity_data = {}
    if os.path.exists(integrity_report_path):
        with open(integrity_report_path, 'r', encoding='utf-8') as f:
            integrity_data = json.load(f)
    else:
        repairs_report["details"].append("No integrity report found to base repairs on.")
        with open(repair_report_path, 'w', encoding='utf-8') as f:
            json.dump(repairs_report, f, indent=2)
        print("Auto-repair completed: No integrity report found.")
        return

    issues_to_fix = integrity_data.get("integrity_check", {}).get("details", [])

    fixed_files = set()

    for issue in issues_to_fix:
        repairs_report["repairs_attempted"] += 1
        if "(daily) might be missing the expected date heading" in issue:
            # Extract file path from issue string
            match = re.search(r"WARNING: (.+? \(daily\))", issue)
            if match:
                file_path_str = match.group(1).replace(" (daily)","")
                file_path = os.path.join("/home/aldan/clawd", file_path_str) # Assuming absolute path from context
                
                if os.path.exists(file_path) and file_path not in fixed_files:
                    try:
                        with open(file_path, 'r+', encoding='utf-8') as f:
                            content = f.read()
                            f.seek(0) # Rewind to beginning

                            # Extract date from filename: YYYY-MM-DD.md
                            filename_match = re.search(r"\d{4}-\d{2}-\d{2}", os.path.basename(file_path))
                            if filename_match:
                                date_heading = f"# {filename_match.group(0)}\n\n"
                                if not content.startswith(date_heading):
                                    f.write(date_heading + content) # Prepend if missing
                                    f.truncate() # Remove old content after new content written
                                    repairs_report["details"].append(f"Fixed missing date heading in {file_path_str}")
                                    repairs_report["repairs_successful"] += 1
                                    fixed_files.add(file_path)
                                else:
                                    repairs_report["details"].append(f"Date heading already present in {file_path_str}, no fix needed.")
                            else:
                                repairs_report["unfixable_issues"].append(f"Could not extract date from filename for {file_path_str}")
                    except Exception as e:
                        repairs_report["unfixable_issues"].append(f"Failed to repair {file_path_str}: {e}")
                elif not os.path.exists(file_path):
                     repairs_report["unfixable_issues"].append(f"File mentioned in issue not found: {file_path_str}")
            else:
                repairs_report["unfixable_issues"].append(f"Failed to parse file path from issue: {issue}")      
        else:
            repairs_report["unfixable_issues"].append(f"Issue not recognized for auto-repair: {issue}")

    with open(repair_report_path, 'w', encoding='utf-8') as f:
        json.dump(repairs_report, f, indent=2)

    print(f"Auto-repair completed. Report saved to {repair_report_path}")

if __name__ == "__main__":
    run_auto_repair()
