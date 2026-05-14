import time

import pytest

from nanobot.pairing import store


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    path = tmp_path / "pairing.json"
    monkeypatch.setattr(store, "_store_path", lambda: path)


class TestGenerateCode:
    def test_format(self) -> None:
        code = store.generate_code("telegram", "123")
        assert len(code) == 9  # 4 + 1 + 4
        assert code[4] == "-"
        assert code.replace("-", "").isalnum()
        assert code.replace("-", "").isupper()

    def test_uniqueness(self) -> None:
        codes = {store.generate_code("telegram", str(i)) for i in range(20)}
        assert len(codes) == 20

    def test_ttl_expiration(self) -> None:
        code = store.generate_code("telegram", "123", ttl=1)
        assert store.approve_code(code) is not None

        code2 = store.generate_code("telegram", "456", ttl=0)
        time.sleep(0.1)
        assert store.approve_code(code2) is None


class TestApproveDeny:
    def test_approve_moves_to_approved(self) -> None:
        code = store.generate_code("telegram", "123")
        assert store.is_approved("telegram", "123") is False

        result = store.approve_code(code)
        assert result == ("telegram", "123")
        assert store.is_approved("telegram", "123") is True
        assert store.get_approved("telegram") == ["123"]

    def test_deny_removes_pending(self) -> None:
        code = store.generate_code("telegram", "123")
        assert store.deny_code(code) is True
        assert store.approve_code(code) is None

    def test_deny_unknown_returns_false(self) -> None:
        assert store.deny_code("UNKNOWN") is False

    def test_approve_expired_returns_none(self) -> None:
        code = store.generate_code("telegram", "123", ttl=0)
        time.sleep(0.1)
        assert store.approve_code(code) is None


class TestRevoke:
    def test_revoke_removes_sender(self) -> None:
        code = store.generate_code("telegram", "123")
        store.approve_code(code)
        assert store.is_approved("telegram", "123") is True

        assert store.revoke("telegram", "123") is True
        assert store.is_approved("telegram", "123") is False
        assert store.get_approved("telegram") == []

    def test_revoke_unknown_returns_false(self) -> None:
        assert store.revoke("telegram", "999") is False


class TestListPending:
    def test_empty(self) -> None:
        assert store.list_pending() == []

    def test_shows_pending(self) -> None:
        store.generate_code("telegram", "123")
        store.generate_code("discord", "456")
        pending = store.list_pending()
        assert len(pending) == 2
        channels = {p["channel"] for p in pending}
        assert channels == {"telegram", "discord"}

    def test_expired_not_listed(self) -> None:
        store.generate_code("telegram", "123", ttl=0)
        time.sleep(0.1)
        assert store.list_pending() == []


class TestHandlePairingCommand:
    def test_list_empty(self) -> None:
        reply = store.handle_pairing_command("telegram", "list")
        assert reply == "No pending pairing requests."

    def test_list_pending(self) -> None:
        store.generate_code("telegram", "123")
        reply = store.handle_pairing_command("telegram", "list")
        assert "Pending pairing requests:" in reply
        assert "telegram" in reply
        assert "123" in reply

    def test_approve(self) -> None:
        code = store.generate_code("telegram", "123")
        reply = store.handle_pairing_command("telegram", f"approve {code}")
        assert "Approved" in reply
        assert "123" in reply
        assert store.is_approved("telegram", "123") is True

    def test_approve_invalid(self) -> None:
        reply = store.handle_pairing_command("telegram", "approve BAD-CODE")
        assert "Invalid or expired" in reply

    def test_approve_no_arg(self) -> None:
        reply = store.handle_pairing_command("telegram", "approve")
        assert "Usage:" in reply

    def test_deny(self) -> None:
        code = store.generate_code("telegram", "123")
        reply = store.handle_pairing_command("telegram", f"deny {code}")
        assert "Denied" in reply
        assert store.approve_code(code) is None

    def test_deny_unknown(self) -> None:
        reply = store.handle_pairing_command("telegram", "deny BAD-CODE")
        assert "not found" in reply

    def test_revoke_current_channel(self) -> None:
        code = store.generate_code("telegram", "123")
        store.approve_code(code)
        reply = store.handle_pairing_command("telegram", "revoke 123")
        assert "Revoked" in reply
        assert store.is_approved("telegram", "123") is False

    def test_revoke_other_channel(self) -> None:
        code = store.generate_code("discord", "456")
        store.approve_code(code)
        # Two-arg form: first arg is channel, second is user
        reply = store.handle_pairing_command("telegram", "revoke discord 456")
        assert "Revoked" in reply
        assert store.is_approved("discord", "456") is False

    def test_revoke_unknown(self) -> None:
        reply = store.handle_pairing_command("telegram", "revoke 999")
        assert "was not in the approved list" in reply

    def test_revoke_no_arg(self) -> None:
        reply = store.handle_pairing_command("telegram", "revoke")
        assert "Usage:" in reply

    def test_unknown_subcommand(self) -> None:
        reply = store.handle_pairing_command("telegram", "foo")
        assert "Unknown pairing command" in reply

    def test_default_to_list(self) -> None:
        store.generate_code("telegram", "123")
        reply = store.handle_pairing_command("telegram", "")
        assert "Pending pairing requests:" in reply


class TestStoreDurability:
    def test_corruption_recovery(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "pairing.json"
        path.write_text("not json{", encoding="utf-8")
        monkeypatch.setattr(store, "_store_path", lambda: path)

        # Should recover gracefully and act as empty store
        assert store.list_pending() == []
        assert store.is_approved("telegram", "123") is False
