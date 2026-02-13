"""
测试自定义provider功能

这个脚本演示如何使用自定义provider功能。
"""

import asyncio
from pathlib import Path

# 添加项目根目录到Python路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from nanobot.config.loader import load_config
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.registry import (
    register_custom_provider,
    find_by_name,
    find_by_model,
    get_all_providers,
    clear_custom_providers,
)


async def test_custom_provider_registration():
    """测试自定义provider注册功能"""
    print("=" * 60)
    print("测试1: 自定义provider注册")
    print("=" * 60)
    
    # 清除之前的自定义provider
    clear_custom_providers()
    
    # 注册一个自定义provider
    custom_spec = register_custom_provider(
        name="test-custom",
        display_name="Test Custom Provider",
        keywords=("test-custom", "test-model"),
        env_key="TEST_CUSTOM_API_KEY",
        litellm_prefix="testcustom",
        is_gateway=False,
        default_api_base="https://api.test-custom.com/v1",
    )
    
    print(f"✓ 注册成功: {custom_spec.name}")
    print(f"  显示名称: {custom_spec.display_name}")
    print(f"  关键词: {custom_spec.keywords}")
    print(f"  LiteLLM前缀: {custom_spec.litellm_prefix}")
    
    # 测试查找
    found = find_by_name("test-custom")
    assert found is not None, "未找到注册的自定义provider"
    print(f"✓ 查找成功: {found.name}")
    
    # 测试通过模型查找
    found_by_model = find_by_model("test-model-v1")
    assert found_by_model is not None, "未通过模型找到自定义provider"
    print(f"✓ 通过模型查找成功: {found_by_model.name}")
    
    # 测试获取所有provider
    all_providers = get_all_providers()
    print(f"✓ 总provider数量: {len(all_providers)}")
    print(f"  内置provider: {len(all_providers) - 1}")
    print(f"  自定义provider: 1")
    
    print()


async def test_config_loading():
    """测试从配置文件加载自定义provider"""
    print("=" * 60)
    print("测试2: 从配置文件加载自定义provider")
    print("=" * 60)
    
    # 清除之前的自定义provider
    clear_custom_providers()
    
    # 加载配置文件
    config_path = Path(__file__).parent / "custom_provider_config.json"
    if not config_path.exists():
        print(f"⚠ 配置文件不存在: {config_path}")
        print("  跳过此测试")
        print()
        return
    
    config = load_config(config_path)
    
    print(f"✓ 配置加载成功")
    print(f"  自定义provider数量: {len(config.providers.custom_providers)}")
    
    # 检查每个自定义provider是否已注册
    for custom_provider in config.providers.custom_providers:
        found = find_by_name(custom_provider.name)
        if found:
            print(f"✓ 已注册: {custom_provider.name} ({found.display_name})")
        else:
            print(f"✗ 未注册: {custom_provider.name}")
    
    print()


async def test_provider_matching():
    """测试provider匹配逻辑"""
    print("=" * 60)
    print("测试3: Provider匹配逻辑")
    print("=" * 60)
    
    # 清除之前的自定义provider
    clear_custom_providers()
    
    # 注册测试provider
    register_custom_provider(
        name="test-provider",
        display_name="Test Provider",
        keywords=("test-provider", "test-model"),
        env_key="TEST_PROVIDER_API_KEY",
        litellm_prefix="testprovider",
        is_gateway=False,
    )
    
    # 加载配置
    config_path = Path(__file__).parent / "custom_provider_config.json"
    if config_path.exists():
        config = load_config(config_path)
    else:
        from nanobot.config.schema import Config
        config = Config()
    
    # 测试匹配
    test_cases = [
        ("test-model-v1", "test-provider"),
        ("my-custom-model", "my-custom-provider"),
        ("unknown-model", None),
    ]
    
    for model, expected_provider in test_cases:
        provider_config, provider_name = config._match_provider(model)
        if expected_provider:
            if provider_name == expected_provider:
                print(f"✓ 匹配成功: {model} → {provider_name}")
            else:
                print(f"✗ 匹配失败: {model} → {provider_name} (期望: {expected_provider})")
        else:
            if provider_name is None:
                print(f"✓ 正确返回None: {model}")
            else:
                print(f"⚠ 意外匹配: {model} → {provider_name}")
    
    print()


async def test_lite_llm_provider():
    """测试LiteLLMProvider与自定义provider的集成"""
    print("=" * 60)
    print("测试4: LiteLLMProvider集成")
    print("=" * 60)
    
    # 清除之前的自定义provider
    clear_custom_providers()
    
    # 注册测试provider
    register_custom_provider(
        name="test-provider",
        display_name="Test Provider",
        keywords=("test-provider", "test-model"),
        env_key="TEST_PROVIDER_API_KEY",
        litellm_prefix="testprovider",
        is_gateway=False,
    )
    
    # 创建provider实例
    provider = LiteLLMProvider(
        api_key="test-key",
        api_base="https://api.test.com/v1",
        default_model="test-model-v1",
        provider_name="test-provider",
    )
    
    print(f"✓ Provider创建成功")
    print(f"  默认模型: {provider.get_default_model()}")
    print(f"  API Base: {provider.api_base}")
    
    # 测试模型解析
    resolved_model = provider._resolve_model("test-model-v1")
    print(f"✓ 模型解析: test-model-v1 → {resolved_model}")
    
    print()


async def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("自定义Provider功能测试")
    print("=" * 60 + "\n")
    
    try:
        await test_custom_provider_registration()
        await test_config_loading()
        await test_provider_matching()
        await test_lite_llm_provider()
        
        print("=" * 60)
        print("✓ 所有测试完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
