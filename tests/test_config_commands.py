"""Tests for config CLI commands."""

import json
from pathlib import Path
from typer.testing import CliRunner

from nanobot.cli.commands import app

runner = CliRunner()


def test_config_template_outputs_valid_json():
    """Test that 'config template' outputs valid JSON."""
    result = runner.invoke(app, ["config", "template"])
    assert result.exit_code == 0
    
    # Should be valid JSON
    output = json.loads(result.stdout)
    assert "agents" in output
    assert "providers" in output
    assert "gateway" in output
    assert "tools" in output


def test_config_template_excludes_channels_by_default():
    """Test that 'config template' excludes channel configs by default."""
    result = runner.invoke(app, ["config", "template"])
    assert result.exit_code == 0
    
    output = json.loads(result.stdout)
    assert "channels" not in output


def test_config_template_includes_channels_with_flag():
    """Test that 'config template --include-channels' includes channel configs."""
    result = runner.invoke(app, ["config", "template", "--include-channels"])
    assert result.exit_code == 0
    
    output = json.loads(result.stdout)
    assert "channels" in output


def test_config_template_writes_to_file(tmp_path: Path):
    """Test that 'config template --output' writes to a file."""
    output_file = tmp_path / "config.template.json"
    result = runner.invoke(app, ["config", "template", "--output", str(output_file)])
    assert result.exit_code == 0
    
    assert output_file.exists()
    content = json.loads(output_file.read_text())
    assert "agents" in content


def test_config_diff_shows_missing_fields(tmp_path: Path):
    """Test that 'config diff' identifies missing fields."""
    config_path = tmp_path / "config.json"
    # Minimal config missing many fields
    config_path.write_text(json.dumps({
        "agents": {
            "defaults": {
                "model": "test-model"
            }
        }
    }))
    
    result = runner.invoke(app, ["config", "diff", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "Missing fields" in result.stdout


def test_config_diff_shows_up_to_date(tmp_path: Path):
    """Test that 'config diff' reports when config is up to date."""
    from nanobot.config.schema import Config
    
    config_path = tmp_path / "config.json"
    # Full default config
    config = Config()
    config_path.write_text(json.dumps(config.model_dump(by_alias=True), indent=2))
    
    result = runner.invoke(app, ["config", "diff", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "up to date" in result.stdout


def test_config_migrate_dry_run(tmp_path: Path):
    """Test that 'config migrate --dry-run' doesn't modify the file."""
    config_path = tmp_path / "config.json"
    original_content = json.dumps({
        "agents": {
            "defaults": {
                "model": "test-model"
            }
        }
    })
    config_path.write_text(original_content)
    
    result = runner.invoke(app, ["config", "migrate", "--dry-run", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "Dry run" in result.stdout
    
    # File should be unchanged
    assert config_path.read_text() == original_content


def test_config_migrate_preserves_existing_values(tmp_path: Path):
    """Test that 'config migrate' preserves user's existing values."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "agents": {
            "defaults": {
                "model": "my-custom-model",
                "maxTokens": 4096
            }
        }
    }))
    
    result = runner.invoke(app, ["config", "migrate", "--config", str(config_path), "--no-backup"])
    assert result.exit_code == 0
    
    migrated = json.loads(config_path.read_text())
    # User's values should be preserved
    assert migrated["agents"]["defaults"]["model"] == "my-custom-model"
    assert migrated["agents"]["defaults"]["maxTokens"] == 4096
    # Missing defaults should be added
    assert "temperature" in migrated["agents"]["defaults"]


def test_config_migrate_preserves_sections_by_default(tmp_path: Path):
    """Test that 'config migrate' doesn't add removed sections by default."""
    config_path = tmp_path / "config.json"
    # Config with only agents section (no providers, tools, etc.)
    config_path.write_text(json.dumps({
        "agents": {
            "defaults": {
                "model": "test-model"
            }
        }
    }))
    
    result = runner.invoke(app, ["config", "migrate", "--config", str(config_path), "--no-backup"])
    assert result.exit_code == 0
    
    migrated = json.loads(config_path.read_text())
    # Should NOT add providers, tools, gateway sections
    assert "providers" not in migrated
    assert "tools" not in migrated
    assert "gateway" not in migrated
    # But should fill in missing agents.defaults fields
    assert "temperature" in migrated["agents"]["defaults"]


def test_config_migrate_add_all_sections(tmp_path: Path):
    """Test that 'config migrate --add-all' adds all missing sections."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "agents": {
            "defaults": {
                "model": "test-model"
            }
        }
    }))
    
    result = runner.invoke(app, ["config", "migrate", "--config", str(config_path), "--no-backup", "--add-all"])
    assert result.exit_code == 0
    
    migrated = json.loads(config_path.read_text())
    # Should add all missing sections
    assert "providers" in migrated
    assert "tools" in migrated
    assert "gateway" in migrated


def test_config_migrate_creates_backup(tmp_path: Path):
    """Test that 'config migrate' creates a backup by default."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "agents": {
            "defaults": {
                "model": "test-model"
            }
        }
    }))
    
    result = runner.invoke(app, ["config", "migrate", "--config", str(config_path)])
    assert result.exit_code == 0
    
    # Backup should exist
    backup_path = config_path.with_suffix(".json.bak")
    assert backup_path.exists()
    assert backup_path.read_text() == config_path.with_suffix(".json.bak").read_text()


def test_config_migrate_no_changes_needed(tmp_path: Path):
    """Test that 'config migrate' handles already-up-to-date configs."""
    from nanobot.config.schema import Config
    
    config_path = tmp_path / "config.json"
    config = Config()
    config_path.write_text(json.dumps(config.model_dump(by_alias=True), indent=2))
    
    result = runner.invoke(app, ["config", "migrate", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "already up to date" in result.stdout


def test_config_migrate_nonexistent_file(tmp_path: Path):
    """Test that 'config migrate' handles missing config file."""
    config_path = tmp_path / "nonexistent.json"
    result = runner.invoke(app, ["config", "migrate", "--config", str(config_path)])
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_config_diff_nonexistent_file(tmp_path: Path):
    """Test that 'config diff' handles missing config file."""
    config_path = tmp_path / "nonexistent.json"
    result = runner.invoke(app, ["config", "diff", "--config", str(config_path)])
    assert result.exit_code == 1
    assert "not found" in result.stdout