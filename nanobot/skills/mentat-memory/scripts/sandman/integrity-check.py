
import os
import json
import re
from datetime import datetime

def run_integrity_check():
    report = {
        "timestamp": datetime.now().isoformat(),
        "sleep_quality": "GOOD",
        "memory_consolidation": {"status": "SKIPPED", "details": "Not directly checked by integrity-check"},
        "integrity_check": {
            "format_issues_found": 0,
            "structural_issues": 0,
            "content_warnings": 0,
            "details": []
        },
        "session_sampling": {"status": "SKIPPED", "details": "Not directly checked by integrity-check"},
        "auto_repairs": {"status": "SKIPPED", "details": "Not directly checked by integrity-check"},
        "recommendations": []
    }

    diary_path = "memory/diary"
    integrity_issues = []

    # Format validation: Basic markdown and date format checks
    for root, _, files in os.walk(diary_path):
        for file in files:
            if not file.endswith(".md"):
                continue
            file_path = os.path.join(root, file)
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

                # Check for empty files
                if not content.strip():
                    integrity_issues.append(f"WARNING: {file_path} is empty.")
                    report["integrity_check"]["content_warnings"] += 1
                    continue

                # Check for basic markdown issues (e.g., headings)
                if re.search(r"^[a-zA-Z0-9].*?\n", content) and not re.match(r"^#{1,6}\s+.*", content):
                    integrity_issues.append(f"WARNING: {file_path} might be missing a top-level heading or has unformatted text at the start.")
                    report["integrity_check"]["format_issues_found"] += 1

                # Check date format in daily files (YYYY-MM-DD.md)
                if "daily" in root and re.match(r"^\d{4}-\d{2}-\d{2}\.md$", file):
                    if not re.search(r"#\s*\d{4}-\d{2}-\d{2}", content):
                        integrity_issues.append(f"WARNING: {file_path} (daily) might be missing the expected date heading.")
                        report["integrity_check"]["format_issues_found"] += 1

    # Structural integrity: Check for consistency in directory structure and file naming
    # This is a basic check. More advanced checks would involve cross-referencing parent directories.
    current_year = str(datetime.now().year) # Assuming current operation year
    
    # Check for annual.md
    if not os.path.exists(os.path.join(diary_path, current_year, "annual.md")):
        integrity_issues.append(f"ERROR: Annual file {os.path.join(diary_path, current_year, 'annual.md')} is missing.")
        report["integrity_check"]["structural_issues"] += 1

    # Update sleep_quality if issues found
    if integrity_issues:
        report["sleep_quality"] = "CRITICAL" if any("ERROR" in issue for issue in integrity_issues) else "ISSUES"
        report["integrity_check"]["details"] = integrity_issues
        report["recommendations"].append("Review integrity check details in the Sandman report for corrective actions.")

    # Save report
    reports_dir = "memory/sandman/reports"
    os.makedirs(reports_dir, exist_ok=True)
    report_filename = os.path.join(reports_dir, f"integrity-{datetime.now().strftime('%Y-%m-%d')}.json")
    with open(report_filename, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    print(f"Integrity check completed. Report saved to {report_filename}")

if __name__ == "__main__":
    run_integrity_check()
