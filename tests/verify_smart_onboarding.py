
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.append(str(Path.cwd()))

from typer.testing import CliRunner
from nanobot.cli.commands import app
from nanobot.agent.tools.cron import CronTool
from nanobot.cron.service import CronService

runner = CliRunner()

def setup_clean_env(tmp_path):
    """Setup a clean environment with no config."""
    config_dir = tmp_path / ".nanobot"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # Mock config paths
    os.environ["NANOBOT_CONFIG_DIR"] = str(config_dir)
    
    # Return paths
    return config_dir

def test_cli_smart_onboarding_system_default(tmp_path):
    """
    Scenario: User has no config. Runs 'cron add'.
    System detects timezone. User accepts it.
    """
    config_dir = setup_clean_env(tmp_path)
    config_file = config_dir / "config.json"
    
    # Mock get_config_path to return our temp path
    with patch("nanobot.config.loader.get_config_path", return_value=config_file), \
         patch("nanobot.utils.helpers.get_workspace_path", return_value=tmp_path / "workspace"):
        
        # Mock datetime to simulate system timezone detection
        mock_dt = MagicMock()
        mock_dt.astimezone.return_value.tzinfo.key = "Europe/London"
        
        with patch("datetime.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            # Also need fromisoformat for the command itself if used
            mock_datetime.fromisoformat = datetime.datetime.fromisoformat
            
            # Run command: Add job at 12:38
            # Input: 'y' (Use Europe/London?), 'y' (Save as default?)
            result = runner.invoke(app, [
                "cron", "add", 
                "--name", "test_job", 
                "--message", "hello", 
                "--at", "2026-02-10T12:38:00",
                "--deliver", "--to", "123", "--channel", "telegram"
            ], input="y\ny\n")
            
            print(f"CLI Output:\n{result.stdout}")
            
            # Verify prompts occurred
            assert "Timezone not configured" in result.stdout
            assert "Use system timezone 'Europe/London'?" in result.stdout
            assert "Saved default timezone: Europe/London" in result.stdout
            
            # Verify Config Saved
            assert config_file.exists()
            data = json.loads(config_file.read_text())
            assert data["agents"]["defaults"]["timezone"] == "Europe/London"

def test_cli_smart_onboarding_manual_entry(tmp_path):
    """
    Scenario: User has no config. Runs 'cron add'.
    System detects wrong timezone. User rejects and enters manual.
    """
    config_dir = setup_clean_env(tmp_path)
    config_file = config_dir / "config.json"
    
    with patch("nanobot.config.loader.get_config_path", return_value=config_file), \
         patch("nanobot.utils.helpers.get_workspace_path", return_value=tmp_path / "workspace"):
        
        mock_dt = MagicMock()
        mock_dt.astimezone.return_value.tzinfo.key = "UTC" # System says UTC
        
        with patch("datetime.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_dt
            
            # Run command
            # Input: 'n' (Don't use UTC), 'Europe/Paris' (Manual), 'y' (Save default)
            result = runner.invoke(app, [
                "cron", "add", 
                "--name", "test_job_2", 
                "--message", "hello", 
                "--cron", "0 9 * * *",
                "--deliver", "--to", "123", "--channel", "telegram"
            ], input="n\nEurope/Paris\ny\n")
            
            print(f"CLI Output:\n{result.stdout}")
            
            assert "Enter timezone (e.g. Europe/Moscow)" in result.stdout
            assert "Saved default timezone: Europe/Paris" in result.stdout
            
            # Verify Config
            data = json.loads(config_file.read_text())
            assert data["agents"]["defaults"]["timezone"] == "Europe/Paris"

def test_agent_tool_behavior_missing_timezone(tmp_path):
    """
    Scenario: Agent calls CronTool WITHOUT timezone argument.
    User has NOT set a default in config.
    """
    # Setup service
    cron_dir = tmp_path / "data" / "cron"
    cron_dir.mkdir(parents=True, exist_ok=True)
    service = CronService(cron_dir / "jobs.json")
    tool = CronTool(service)
    
    # Mock context
    tool.set_context("telegram", "123")
    
    # 1. Test: Agent adds job with ISO time, NO timezone
    # This simulates "Remind me at 12:38" -> translated to ISO by Agent, but Agent forgot TZ
    print("\n--- Agent Tool Test: ISO Time, No TZ ---")
    iso_time = "2026-02-10T12:38:00"
    
    # We need to run async
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    result = loop.run_until_complete(tool.execute(
        action="add",
        message="Test Message",
        cron_expr=iso_time,
        timezone=None, # MISSING!
        type="echo"
    ))
    
    print(f"Tool Result: {result}")
    
    # ASSERTION: Must return ERROR string now
    if "Error: 'timezone' argument is REQUIRED" in result:
        print("SUCCESS: Tool rejected missing timezone with helpful error.")
    else:
        print(f"FAILURE: Tool did not reject missing timezone. Result: {result}")

    # Verify no job was created
    jobs = loop.run_until_complete(service.list_jobs())
    if not jobs:
        print("SUCCESS: No invalid job created.")
    else:
        print("FAILURE: Invalid job was created!")

import datetime

if __name__ == "__main__":
    import pytest
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
