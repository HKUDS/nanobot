from typer.testing import CliRunner

from nanobot.cli.commands import app

runner = CliRunner()


def test_cron_add_rejects_invalid_timezone(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.config.loader.get_data_dir", lambda: tmp_path)

    result = runner.invoke(
        app,
        [
            "cron",
            "add",
            "--name",
            "demo",
            "--message",
            "hello",
            "--cron",
            "0 9 * * *",
            "--tz",
            "America/Vancovuer",
        ],
    )

    assert result.exit_code == 1
    assert "Error: unknown timezone 'America/Vancovuer'" in result.stdout
    assert not (tmp_path / "cron" / "jobs.json").exists()
