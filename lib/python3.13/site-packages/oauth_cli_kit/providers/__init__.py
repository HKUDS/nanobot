"""OAuth Provider 配置集合。

设计目标：
1) 让 codex / Claude Code 等多个 CLI 的 OAuth 配置以“providers 子包”统一管理；
2) 保持现有对外 API（例如 oauth_cli_kit.constants.OPENAI_CODEX_PROVIDER）不变；
3) 后续新增 provider 时，只需在本目录新增一个模块并在此处导出即可。
"""

from oauth_cli_kit.providers.openai_codex import OPENAI_CODEX_PROVIDER

__all__ = [
    "OPENAI_CODEX_PROVIDER",
]

