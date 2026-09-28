"""Contributor refreshes must preserve credit when GitHub omits an account."""

import pytest

from scripts import update_readme_contributors as updater


def test_refresh_preserves_missing_contributor_and_is_idempotent(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    existing = {
        "contributions": 5,
        "login": "Existing",
        "type": "User",
        "html_url": "https://github.com/Existing",
        "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
    }
    newcomer = {
        "contributions": 2,
        "login": "Newcomer",
        "type": "User",
        "html_url": "https://github.com/Newcomer",
        "avatar_url": "https://avatars.githubusercontent.com/u/2?v=4",
    }
    original = f"# Thanks 🤝\n{updater.render_wall([existing])}\nFooter\n"
    readme.write_text(original, encoding="utf-8")
    monkeypatch.setattr(updater, "README", readme)
    def fetch_pages(endpoint, **params):
        if endpoint == "contributors":
            assert params == {"anon": "1"}
            return [newcomer, {"type": "Anonymous", "email": "old@example.com", "contributions": 3},
                    {"type": "Anonymous", "email": "other@example.com", "contributions": 2}]
        assert endpoint == "commits" and params == {"author": "Existing"}
        return [{"commit": {"author": {"email": email}}}
                for email in ["old@example.com", "old@example.com", "other@example.com"]]

    monkeypatch.setattr(updater, "fetch_pages", fetch_pages)

    with pytest.raises(SystemExit, match="out of date"):
        updater.update_readme(check=True)
    assert readme.read_text(encoding="utf-8") == original

    assert updater.update_readme(check=False)
    updated = readme.read_text(encoding="utf-8")
    assert updated.count('alt="Existing"') == 1
    assert updated.count('alt="Newcomer"') == 1
    assert updated.index('alt="Existing"') < updated.index('alt="Newcomer"')
    assert updated.startswith("# Thanks 🤝\n")
    assert updated.endswith("\nFooter\n")
    assert not updater.update_readme(check=True)

    # An account returning to the API must not be duplicated by retained credit.
    monkeypatch.setattr(updater, "fetch_pages", lambda *args, **kwargs: [newcomer, existing])
    assert not updater.update_readme(check=True)


def test_equal_counts_keep_previous_order():
    contributors = [updater.Contributor(
        login=name, type="User", html_url=f"https://github.com/{name}",
        avatar_url=f"https://avatars.githubusercontent.com/u/{i}?v=4", contributions=1,
    ) for i, name in enumerate(["First", "Second", "Third"])]
    previous = updater.render_wall(contributors[:2])
    assert updater.render_wall(list(reversed(contributors)), previous) == updater.render_wall(contributors)


def test_unresolved_count_does_not_overwrite_readme(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    original = (f'{updater.START}\n<p>\n'
                '<a href="https://github.com/Missing"><img src="https://example.com/a?s=48" '
                'width="48" height="48" alt="Missing"></a>\n'
                f'</p>\n{updater.END}\n')
    readme.write_text(original, encoding="utf-8")
    monkeypatch.setattr(updater, "README", readme)
    monkeypatch.setattr(updater, "fetch_pages", lambda *args, **kwargs: [])
    with pytest.raises(SystemExit, match="Cannot resolve contribution count for Missing"):
        updater.update_readme(check=False)
    assert readme.read_text(encoding="utf-8") == original
