"""Tests for heartbeat context bridge — injecting delivered messages into channel session."""

from nanobot.session.manager import SessionManager


class TestHeartbeatContextBridge:
    """Verify that on_heartbeat_notify injects the assistant message into the
    channel session so user replies have conversational context."""

    def test_notify_injects_into_channel_session(self, tmp_path):
        """After notify, the target channel session should contain the
        heartbeat response as an assistant turn."""
        session_mgr = SessionManager(tmp_path / "sessions")
        target_key = "telegram:12345"

        # Simulate: session exists with one user message
        target_session = session_mgr.get_or_create(target_key)
        target_session.add_message("user", "hello earlier")
        session_mgr.save(target_session)

        # Simulate what on_heartbeat_notify does
        target_session = session_mgr.get_or_create(target_key)
        target_session.add_message(
            "assistant",
            "3 new emails — invoice, meeting, proposal.",
            _channel_delivery=True,
        )
        session_mgr.save(target_session)

        # Reload and verify
        reloaded = session_mgr.get_or_create(target_key)
        messages = reloaded.get_history(max_messages=0)
        roles = [m["role"] for m in messages]
        assert roles == ["user", "assistant"]
        assert "3 new emails" in messages[-1]["content"]

    def test_reply_after_injection_has_context(self, tmp_path):
        """Simulates the full flow: prior conversation exists, heartbeat
        injects, then user replies.  The session should have the heartbeat
        message visible in get_history so the model sees the context."""
        session_mgr = SessionManager(tmp_path / "sessions")
        target_key = "telegram:12345"

        # Pre-existing conversation (user has chatted before)
        session = session_mgr.get_or_create(target_key)
        session.add_message("user", "Hey")
        session.add_message("assistant", "Hi there!")
        session_mgr.save(session)

        # Step 1: heartbeat injects assistant message
        session = session_mgr.get_or_create(target_key)
        session.add_message(
            "assistant",
            "If you want, I can mark that email as read.",
            _channel_delivery=True,
        )
        session_mgr.save(session)

        # Step 2: user replies "Sure"
        session = session_mgr.get_or_create(target_key)
        session.add_message("user", "Sure")
        session_mgr.save(session)

        # Verify: get_history includes the heartbeat injection
        reloaded = session_mgr.get_or_create(target_key)
        history = reloaded.get_history(max_messages=0)
        roles = [m["role"] for m in history]
        assert roles == ["user", "assistant", "assistant", "user"]
        assert "mark that email" in history[2]["content"]
        assert history[3]["content"] == "Sure"

    def test_injection_does_not_duplicate_on_existing_history(self, tmp_path):
        """If the channel session already has messages, the injection
        appends cleanly without corruption."""
        session_mgr = SessionManager(tmp_path / "sessions")
        target_key = "telegram:12345"

        # Pre-existing conversation
        session = session_mgr.get_or_create(target_key)
        session.add_message("user", "What time is it?")
        session.add_message("assistant", "It's 2pm.")
        session.add_message("user", "Thanks")
        session_mgr.save(session)

        # Heartbeat injects
        session = session_mgr.get_or_create(target_key)
        session.add_message(
            "assistant",
            "You have a meeting in 30 minutes.",
            _channel_delivery=True,
        )
        session_mgr.save(session)

        # Verify
        reloaded = session_mgr.get_or_create(target_key)
        history = reloaded.get_history(max_messages=0)
        roles = [m["role"] for m in history]
        assert roles == ["user", "assistant", "user", "assistant"]
        assert "meeting in 30 minutes" in history[-1]["content"]

    def test_reply_after_injection_to_empty_session_keeps_context(self, tmp_path):
        """A user replying to the first delivered message still sees that context."""
        session_mgr = SessionManager(tmp_path / "sessions")
        target_key = "telegram:99999"

        session = session_mgr.get_or_create(target_key)
        session.add_message(
            "assistant",
            "Weather alert: sandstorm expected at 4pm.",
            _channel_delivery=True,
        )
        session.add_message("user", "Sure")
        session_mgr.save(session)

        reloaded = session_mgr.get_or_create(target_key)
        history = reloaded.get_history(max_messages=0)
        assert len(history) == 2
        assert history[0]["role"] == "assistant"
        assert "sandstorm" in history[0]["content"]
        assert history[1] == {"role": "user", "content": "Sure"}
