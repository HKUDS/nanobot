
import json
import os
from datetime import datetime

def generate_morning_report():
    today_str = datetime.now().strftime('%Y-%m-%d')
    reports_dir = "memory/sandman/reports"

    report_filename = os.path.join(reports_dir, f"morning-{today_str}.md")
    integrity_report_path = os.path.join(reports_dir, f"integrity-{today_str}.json")
    
    integrity_data = {}
    if os.path.exists(integrity_report_path):
        with open(integrity_report_path, 'r', encoding='utf-8') as f:
            integrity_data = json.load(f)

    # Determining overall sleep quality
    sleep_quality = integrity_data.get("sleep_quality", "GOOD")
    if sleep_quality == "CRITICAL":
        emoji = "🚨 CRITICAL"
    elif sleep_quality == "ISSUES":
        emoji = "⚠️ ISSUES"
    else:
        emoji = "✅ GOOD"

    report_content = f"""
# Sandman Report - {today_str}

## Sleep Quality: {emoji}

### Memory Consolidation
- Daily → Weekly: {integrity_data.get("memory_consolidation", {}).get("status", "Not Run")}
- Details: {integrity_data.get("memory_consolidation", {}).get("details", "N/A")}

### Integrity Check
- Format issues found: {integrity_data.get("integrity_check", {}).get("format_issues_found", "N/A")}
- Structural issues: {integrity_data.get("integrity_check", {}).get("structural_issues", "N/A")}
- Content warnings: {integrity_data.get("integrity_check", {}).get("content_warnings", "N/A")}
"""

    if integrity_data.get("integrity_check", {}).get("details"):
        report_content += "\n#### Integrity Check Details:\n"
        for detail in integrity_data["integrity_check"]["details"]:
            report_content += f"- {detail}\n"

    report_content += f"""

### Session Sampling
- Status: {integrity_data.get("session_sampling", {}).get("status", "Not Run")}
- Details: {integrity_data.get("session_sampling", {}).get("details", "N/A")}

### Auto-Repairs
- Status: {integrity_data.get("auto_repairs", {}).get("status", "Not Run")}
- Details: {integrity_data.get("auto_repairs", {}).get("details", "N/A")}

### Recommendations
"""
    recommendations = integrity_data.get("recommendations", [])
    if recommendations:
        for rec in recommendations:
            report_content += f"- {rec}\n"
    else:
        report_content += "None\n"
            
    report_content += f"""

---
Detailed logs: memory/sandman/reports/
"""

    with open(report_filename, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f"Morning report generated and saved to {report_filename}")

if __name__ == "__main__":
    generate_morning_report()
