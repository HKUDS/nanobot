"""Service installation preserves interpreter identity and systemd argument boundaries."""

import sys
from pathlib import Path

from nanobot.operations.install import install_supervisor, systemd_argument


def test_systemd_arguments_escape_expansion_and_quotes():
    assert systemd_argument('/some path/%thing/$VAR/"quoted"') == '"/some path/%%thing/$$VAR/\\"quoted\\""'


def test_installer_renders_real_templates_idempotently_without_touching_wireguard(tmp_path):
    config = tmp_path / "instance config.json"
    config.write_text("{}", encoding="utf-8")
    target = tmp_path / "units"
    source = Path(__file__).resolve().parents[2]
    arguments = dict(source=source, config=config, python=Path(sys.executable),
                     directory=target, activate=False)
    install_supervisor(**arguments)
    before = {path.name: path.read_text(encoding="utf-8") for path in target.iterdir()}
    install_supervisor(**arguments)
    after = {path.name: path.read_text(encoding="utf-8") for path in target.iterdir()}
    assert before == after
    assert "@PYTHON@" not in after["nanobot-supervisor.service"]
    assert str(config) in after["nanobot-supervisor.service"]
    assert "OnCalendar=*:0/10" in after["nanobot-supervisor.timer"]
    assert set(after) == {"nanobot-supervisor.service", "nanobot-supervisor.timer"}
