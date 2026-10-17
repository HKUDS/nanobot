"""Exact instance paths for third-party OAuth token storage."""

# pyright: reportMissingTypeStubs=false

from pathlib import Path

from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
from oauth_cli_kit.storage import FileTokenStorage

from nanobot.config.home import get_home_path


class InstanceTokenStorage(FileTokenStorage):
    """Keep library serialization and refresh locking without shared-user fallback."""

    def __init__(self, path: Path) -> None:
        super().__init__(import_codex_cli=False)
        self._path = path.expanduser().resolve()

    def get_token_path(self) -> Path:
        return self._path


def codex_token_storage(home: Path | None = None) -> InstanceTokenStorage:
    return InstanceTokenStorage((home or get_home_path()) / "auth" / OPENAI_CODEX_PROVIDER.token_filename)
