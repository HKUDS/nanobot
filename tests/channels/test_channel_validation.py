from __future__ import annotations

import pytest

from nanobot.channels import validation


def test_probe_tcp_connects_to_the_validated_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    connected: list[tuple[str, int]] = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        validation,
        "resolve_url_target",
        lambda *_args, **_kwargs: (True, "", ("203.0.113.10",)),
    )
    monkeypatch.setattr(
        validation.socket,
        "create_connection",
        lambda target, **_kwargs: connected.append(target) or FakeSocket(),
    )

    validation.probe_tcp("mail.example.com", 2525)

    assert connected == [("203.0.113.10", 2525)]
