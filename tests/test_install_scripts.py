from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _post_install_section(path: str, marker: str) -> str:
    script = (ROOT / path).read_text(encoding="utf-8")
    return script.split(marker, 1)[1]


def test_shell_installer_skips_before_browser_and_probes_webui() -> None:
    section = _post_install_section("scripts/install.sh", 'info "Installed nanobot:"')

    assert section.index('NANOBOT_SKIP_WIZARD:-}" = "1"') < section.index(
        "if has_browser_session"
    )
    assert "if run_nanobot webui --help >/dev/null 2>&1; then" in section
    assert "Falling back to the setup wizard..." in section


def test_powershell_installer_skips_before_browser_and_probes_webui() -> None:
    section = _post_install_section("scripts/install.ps1", 'Write-Info "Installed nanobot:"')

    assert section.index('$env:NANOBOT_SKIP_WIZARD -eq "1"') < section.index(
        "if (Test-BrowserSession)"
    )
    assert 'Invoke-Nanobot @("webui", "--help") *> $null' in section
    assert "Falling back to the setup wizard..." in section
