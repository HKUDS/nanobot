from nanobot.agent.skills import BUILTIN_SKILLS_DIR


def test_weather_skill_uses_windows_safe_single_today_request() -> None:
    content = (BUILTIN_SKILLS_DIR / "weather" / "SKILL.md").read_text(encoding="utf-8")
    normalized = " ".join(content.split())

    assert "On Windows PowerShell, use `curl.exe`" in normalized
    assert "bare `curl` may resolve to `Invoke-WebRequest`" in normalized
    assert "https://wttr.in/London?1&m" in content
    assert 'curl.exe -s "https://wttr.in/Berlin.png" -o weather.png' in content
    assert "/tmp/weather.png" not in content
    assert (
        "Do not fetch current conditions separately when a today or forecast "
        "request already includes them."
    ) in normalized
