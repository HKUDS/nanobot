"""Tests for abbreviate_path utility."""

import os
from nanobot.utils.path import abbreviate_path


class TestAbbreviatePathShort:
    def test_short_path_unchanged(self):
        assert abbreviate_path("/home/user/file.py") == "/home/user/file.py"

    def test_exact_max_len_unchanged(self):
        path = "/a/b/c"  # 7 chars
        assert abbreviate_path("/a/b/c", max_len=7) == "/a/b/c"

    def test_basename_only(self):
        assert abbreviate_path("file.py") == "file.py"

    def test_empty_string(self):
        assert abbreviate_path("") == ""


class TestAbbreviatePathHome:
    def test_home_replacement(self):
        home = os.path.expanduser("~")
        result = abbreviate_path(f"{home}/project/file.py")
        assert result.startswith("~/")
        assert result.endswith("file.py")

    def test_home_preserves_short_path(self):
        home = os.path.expanduser("~")
        result = abbreviate_path(f"{home}/a.py")
        assert result == "~/a.py"


class TestAbbreviatePathLong:
    def test_long_path_keeps_basename(self):
        path = "/a/b/c/d/e/f/g/h/very_long_filename.py"
        result = abbreviate_path(path, max_len=30)
        assert result.endswith("very_long_filename.py")
        assert "\u2026" in result

    def test_long_path_keeps_parent_dir(self):
        path = "/a/b/c/d/e/f/g/h/src/loop.py"
        result = abbreviate_path(path, max_len=30)
        assert "loop.py" in result
        assert "src" in result

    def test_very_long_path_just_basename(self):
        path = "/a/b/c/d/e/f/g/h/i/j/k/l/m/n/o/p/q/r/s/t/u/v/w/x/y/z/file.py"
        result = abbreviate_path(path, max_len=20)
        assert result.endswith("file.py")
        assert len(result) <= 20


class TestAbbreviatePathWindows:
    def test_windows_drive_path(self):
        path = "D:\\Documents\\GitHub\\nanobot\\src\\utils\\helpers.py"
        result = abbreviate_path(path, max_len=40)
        assert result.endswith("helpers.py")
        assert "nanobot" in result

    def test_windows_home(self):
        home = os.path.expanduser("~")
        path = os.path.join(home, ".nanobot", "workspace", "log.txt")
        result = abbreviate_path(path)
        assert result.startswith("~/")
        assert "log.txt" in result


class TestAbbreviatePathURLs:
    def test_url_keeps_domain_and_filename(self):
        url = "https://example.com/api/v2/long/path/resource.json"
        result = abbreviate_path(url, max_len=40)
        assert "resource.json" in result
        assert "example.com" in result

    def test_short_url_unchanged(self):
        url = "https://example.com/api"
        assert abbreviate_path(url) == url
