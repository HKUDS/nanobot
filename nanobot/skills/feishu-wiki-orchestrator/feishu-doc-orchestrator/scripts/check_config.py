#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书配置检查工具
验证 config/feishu.json + ~/.nanobot/.env 配置是否正确
"""

import sys
from pathlib import Path

# 添加技能目录到路径
sys.path.insert(0, '.claude/skills/feishu-doc-creator-with-permission/scripts')

from doc_creator_with_permission import load_config, get_access_token
import requests


def check_config():
    """检查飞书配置"""

    print("=" * 60)
    print("飞书配置检查工具")
    print("=" * 60)

    # 加载配置
    config = load_config()

    # 必需配置项
    required_configs = {
        'FEISHU_APP_ID': '应用ID（从飞书开放平台获取）',
        'FEISHU_APP_SECRET': '应用密钥（从飞书开放平台获取）',
        'FEISHU_API_DOMAIN': 'API域名',
    }

    # 推荐配置项
    recommended_configs = {
        'FEISHU_AUTO_COLLABORATOR_ID': '协作者ID（自动添加文档权限）',
        'FEISHU_DEFAULT_FOLDER': '默认文件夹Token（新文档保存在此文件夹）',
    }

    all_ok = True

    print("\n[检查1] 必需配置项")
    print("-" * 40)

    for key, desc in required_configs.items():
        value = config.get(key, '')
        if value:
            # 部分隐藏敏感信息
            if 'SECRET' in key or 'ID' in key:
                display_value = value[:8] + '...' if len(value) > 8 else '***'
            else:
                display_value = value
            print(f"  [OK] {key}: {display_value}")
            print(f"     说明: {desc}")
        else:
            print(f"  [FAIL] {key}: 未配置")
            print(f"     说明: {desc}")
            print(f"     影响: 无法使用技能")
            all_ok = False

    print("\n[检查2] 推荐配置项")
    print("-" * 40)

    for key, desc in recommended_configs.items():
        value = config.get(key, '')
        if value:
            # 部分隐藏敏感信息
            if 'ID' in key or 'TOKEN' in key:
                display_value = value[:8] + '...' if len(value) > 8 else '***'
            else:
                display_value = value
            print(f"  [OK] {key}: {display_value}")
            print(f"     说明: {desc}")
        else:
            print(f"  [WARN]  {key}: 未配置")
            print(f"     说明: {desc}")
            print(f"     影响: 部分功能无法使用")

    print("\n[检查3] API 连接测试")
    print("-" * 40)

    if config.get('FEISHU_APP_ID') and config.get('FEISHU_APP_SECRET'):
        try:
            print("  正在测试API连接...")
            token = get_access_token(config, use_user_token=False)
            if token:
                print("  [OK] API连接正常")
                print("     应用凭证有效")
            else:
                print("  [FAIL] API连接失败")
                print("     可能原因：应用ID或密钥错误")
                all_ok = False
        except Exception as e:
            print(f"  [FAIL] API连接失败: {e}")
            print("     可能原因：网络问题或配置错误")
            all_ok = False
    else:
        print("  [WARN]  跳过API测试（缺少必需配置）")

    print("\n" + "=" * 60)

    if all_ok:
        print("[OK] 配置检查通过！技能可以正常使用。")
        print()
        print("使用方法：")
        print("  请帮我将 docs/example.md 转换为飞书文档")
        return 0
    else:
        print("[FAIL] 配置检查失败！请完成以下步骤：")
        print()
        print("1. 访问飞书开放平台：https://open.feishu.cn/")
        print("2. 创建自建应用，获取 APP_ID 和 APP_SECRET")
        print("3. 编辑配置文件：~/.nanobot/.env")
        print("4. 重新运行检查：python skills/feishu-wiki-orchestrator/feishu-doc-orchestrator/scripts/check_config.py")
        return 1


if __name__ == "__main__":
    sys.exit(check_config())
