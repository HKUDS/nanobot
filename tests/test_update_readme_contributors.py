"""Contributor refreshes must preserve credit when GitHub omits an account."""

import pytest

from scripts import update_readme_contributors as updater


def test_refresh_preserves_missing_contributor_and_is_idempotent(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    existing = {
        "login": "Existing",
        "type": "User",
        "html_url": "https://github.com/Existing",
        "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
    }
    newcomer = {
        "login": "Newcomer",
        "type": "User",
        "html_url": "https://github.com/Newcomer",
        "avatar_url": "https://avatars.githubusercontent.com/u/2?v=4",
    }
    original = f"# Thanks 🤝\n{updater.render_wall([existing])}\nFooter\n"
    readme.write_text(original, encoding="utf-8")
    monkeypatch.setattr(updater, "README", readme)
    monkeypatch.setattr(updater, "fetch_contributors", lambda: [newcomer])

    with pytest.raises(SystemExit, match="out of date"):
        updater.update_readme(check=True)
    assert readme.read_text(encoding="utf-8") == original

    assert updater.update_readme(check=False)
    updated = readme.read_text(encoding="utf-8")
    assert updated.count('alt="Existing"') == 1
    assert updated.count('alt="Newcomer"') == 1
    assert updated.startswith("# Thanks 🤝\n")
    assert updated.endswith("\nFooter\n")
    assert not updater.update_readme(check=True)

    # An account returning to the API must not be duplicated by retained credit.
    monkeypatch.setattr(updater, "fetch_contributors", lambda: [newcomer, existing])
    assert not updater.update_readme(check=True)
