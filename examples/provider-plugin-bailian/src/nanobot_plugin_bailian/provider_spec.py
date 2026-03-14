"""ProviderSpec definitions for Alibaba Cloud BaiLian (DashScope)."""

from nanobot.providers.registry import ProviderSpec

# This plugin demonstrates how DashScope/BaiLian can be provided by an external
# package instead of being hardcoded in nanobot's built-in provider list.
BAILIAN_SPEC = ProviderSpec(
    name="aliyun_bailian",
    keywords=("aliyun_bailian", "dashscope", "bailian", "qwen"),
    env_key="DASHSCOPE_API_KEY",
    display_name="Alibaba BaiLian",
    litellm_prefix="dashscope",
    skip_prefixes=("dashscope/",),
    env_extras=(
        ("DASHSCOPE_API_BASE", "{api_base}"),
    ),
    default_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
)


def get_provider_specs() -> list[ProviderSpec]:
    """Entry point target for `nanobot.provider_specs`."""
    return [BAILIAN_SPEC]
