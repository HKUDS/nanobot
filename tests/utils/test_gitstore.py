from nanobot.utils.gitstore import CommitInfo


class TestCommitInfo:
    def test_format_with_empty_message(self):
        commit = CommitInfo(sha="abcd1234", message="", timestamp="2026-04-04 12:00")
        result = commit.format()
        assert "(no message)" in result or "## " in result

    def test_format_with_message(self):
        commit = CommitInfo(sha="abcd1234", message="dream: update", timestamp="2026-04-04 12:00")
        result = commit.format()
        assert "dream: update" in result
