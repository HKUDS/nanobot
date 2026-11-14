"""Google service-account helpers and ID parsing used by the Drive tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.tools import _google
from nanobot.agent.tools._google import require_google_deps, service_account_email_hint
from nanobot.agent.tools.google_config import normalize_google_ids


def _key(**overrides: object) -> dict[str, object]:
    return {
        "type": "service_account",
        "client_email": "bot@example.iam.gserviceaccount.com",
        "private_key": "test-key",
        **overrides,
    }


def test_normalize_ids_splits_a_list_string_and_drops_duplicates() -> None:
    assert normalize_google_ids(["a1, b2\nc3", "a1", " "], kind="Drive folder") == ["a1", "b2", "c3"]


def test_normalize_ids_rejects_a_url() -> None:
    with pytest.raises(ValueError, match="invalid Drive folder id"):
        normalize_google_ids(["https://drive.google.com/drive/folders/abc"], kind="Drive folder")


def test_email_hint_reads_a_service_account_key(tmp_path: Path) -> None:
    key = tmp_path / "sa.json"
    key.write_text(json.dumps(_key()), encoding="utf-8")

    assert service_account_email_hint(key) == "bot@example.iam.gserviceaccount.com"


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        json.dumps([]),
        json.dumps(_key(type="authorized_user")),
        json.dumps(_key(client_email="")),
        json.dumps(_key(private_key=None)),
    ],
)
def test_email_hint_is_none_unless_the_file_is_a_service_account_key(
    raw: str,
    tmp_path: Path,
) -> None:
    key = tmp_path / "sa.json"
    key.write_text(raw, encoding="utf-8")

    assert service_account_email_hint(key) is None
    assert service_account_email_hint(tmp_path / "missing.json") is None


def test_missing_libraries_name_the_extra_to_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_module(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr(_google.importlib, "import_module", _no_module)

    with pytest.raises(RuntimeError, match="Google Drive support is not installed.*enable drive"):
        require_google_deps("Google Drive", "drive")
