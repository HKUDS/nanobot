"""OpenAI Codex OAuth token storage."""

# oauth-cli-kit does not publish type stubs.
# pyright: reportMissingTypeStubs=false

from oauth_cli_kit.providers import OPENAI_CODEX_PROVIDER
from oauth_cli_kit.storage import FileTokenStorage

from nanobot.config.paths import get_data_dir


def get_openai_codex_storage() -> FileTokenStorage:
    return FileTokenStorage(
        token_filename=OPENAI_CODEX_PROVIDER.token_filename,
        data_dir=get_data_dir(),
    )
