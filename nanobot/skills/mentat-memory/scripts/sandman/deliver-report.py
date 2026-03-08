import os
import json
from datetime import datetime

# Assuming message tool is available in the environment
# We'll use a placeholder for print(default_api.message(...)) for now

def deliver_morning_report():
    today_str = datetime.now().strftime('%Y-%m-%d')
    reports_dir = "memory/sandman/reports"

    # Read the generated morning report markdown
    morning_report_path = os.path.join(reports_dir, f"morning-{today_str}.md")
    report_content = "No morning report generated yet." # Default content
    if os.path.exists(morning_report_path):
        with open(morning_report_path, 'r', encoding='utf-8') as f:
            report_content = f.read()

    # Read the integrity data to check sleep_quality for conditional delivery
    integrity_report_path = os.path.join(reports_dir, f"integrity-{today_str}.json")
    integrity_data = {}
    if os.path.exists(integrity_report_path):
        with open(integrity_report_path, 'r', encoding='utf-8') as f:
            integrity_data = json.load(f)
    
    sleep_quality = integrity_data.get("sleep_quality", "GOOD")

    # Load Sandman config for reporting preferences
    config_path = "memory/sandman/config.json"
    config = {"reporting": {"silent_if_clean": True, "notify_on_severity": ["warning", "critical"], "delivery_method": "telegram"}}
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    
    reporting_config = config.get("reporting", {})
    silent_if_clean = reporting_config.get("silent_if_clean", True)
    notify_on_severity = reporting_config.get("notify_on_severity", ["warning", "critical"])

    should_notify = False
    if sleep_quality == "CRITICAL":
        should_notify = True
    elif sleep_quality == "ISSUES" and ("warning" in notify_on_severity or "critical" in notify_on_severity):
        should_notify = True
    elif sleep_quality == "GOOD" and not silent_if_clean:
        should_notify = True
    
    if should_notify:
        # Placeholder for actual message tool call
        # In a real Clawdbot environment, this would be:
        # print(default_api.message(action='send', to='Josiah', message=report_content, channel='telegram'))
        print(f"[SIMULATED MESSAGE SEND]: Delivering report to Josiah via Telegram.\n---\n{report_content}\n---")
    else:
        print("Report not delivered: Sleep quality was GOOD and silent_if_clean is True.")

if __name__ == "__main__":
    deliver_morning_report()
