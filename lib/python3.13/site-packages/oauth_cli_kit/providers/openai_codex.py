"""OpenAI Codex CLI 的默认 OAuth Provider 配置。"""

from __future__ import annotations

from oauth_cli_kit.models import OAuthProviderConfig


# 注意：这里仅组织配置位置（从 constants.py 挪到 providers/），不改变任何字段/逻辑。
OPENAI_CODEX_PROVIDER = OAuthProviderConfig(
    client_id="app_EMoamEEZ73f0CkXaXp7hrann",
    authorize_url="https://auth.openai.com/oauth/authorize",
    token_url="https://auth.openai.com/oauth/token",
    redirect_uri="http://localhost:1455/auth/callback",
    scope="openid profile email offline_access",
    jwt_claim_path="https://api.openai.com/auth",
    account_id_claim="chatgpt_account_id",
    default_originator="nanobot",
    token_filename="codex.json",
)

