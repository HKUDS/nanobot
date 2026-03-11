#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档创建器 - 简化版
使用 tenant_access_token 创建文档，不需要 SDK
输出：doc_info.json
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime
import requests


def load_config():
    """从环境变量加载飞书配置"""
    import os
    config = {
        'FEISHU_APP_ID': os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_ID', ''),
        'FEISHU_APP_SECRET': os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_SECRET', ''),
        'FEISHU_API_DOMAIN': os.environ.get('FEISHU_API_DOMAIN', 'https://open.feishu.cn'),
        'FEISHU_DEFAULT_FOLDER': os.environ.get('FEISHU_DEFAULT_FOLDER', ''),
        'FEISHU_AUTO_COLLABORATOR_ID': os.environ.get('FEISHU_AUTO_COLLABORATOR_ID', ''),
    }
    if not config['FEISHU_APP_ID'] or not config['FEISHU_APP_SECRET']:
        raise Exception("缺少飞书凭据，请设置环境变量 NANOBOT_CHANNELS__FEISHU__APP_ID / NANOBOT_CHANNELS__FEISHU__APP_SECRET")
    return config


def get_access_token(config):
    """获取 tenant_access_token"""
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    payload = {
        "app_id": config['FEISHU_APP_ID'],
        "app_secret": config['FEISHU_APP_SECRET']
    }
    response = requests.post(url, json=payload, headers=headers)
    result = response.json()
    if result.get("code") == 0:
        return result["tenant_access_token"]
    else:
        raise Exception(f"获取 token 失败: {result}")


def create_document(token, config, title):
    """创建飞书文档"""
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "title": title,
        "folder_token": config.get('FEISHU_DEFAULT_FOLDER', '')
    }

    response = requests.post(url, json=payload, headers=headers)
    result = response.json()

    if result.get("code") == 0:
        return result["data"]["document"]["document_id"]
    else:
        raise Exception(f"创建文档失败: {result}")


def add_collaborator(token, config, document_id, user_id, user_type, perm):
    """添加协作者权限 - 必须使用 tenant_access_token"""
    import urllib.parse
    params = urllib.parse.urlencode({"type": "docx"})
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/drive/v1/permissions/{document_id}/members?{params}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "member_id": user_id,
        "member_type": user_type,
        "perm": perm
    }

    response = requests.post(url, json=payload, headers=headers)
    result = response.json()

    if result.get("code") == 0:
        return result
    else:
        raise Exception(f"添加权限成员失败: {result}")


def main():
    """主函数"""
    title = "飞书文档完整测试-25种块类型"
    output_dir = Path("workflow/step2_create")

    # 加载配置
    config = load_config()
    if not config:
        print("[ERROR] Unable to load config")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Feishu Document Creator - Simplified Version")
    print("=" * 70)
    print(f"Title: {title}")
    print()

    # 创建文档
    print("[Step 1/2] Creating document...")
    try:
        token = get_access_token(config)
        doc_id = create_document(token, config, title)
        print(f"[OK] Document created: {doc_id}")
    except Exception as e:
        print(f"[FAIL] Create document failed: {e}")
        sys.exit(1)

    # 添加协作者
    print("\n[Step 2/2] Adding collaborator...")
    collaborator_id = config.get('FEISHU_AUTO_COLLABORATOR_ID')
    if collaborator_id:
        try:
            add_collaborator(token, config, doc_id,
                collaborator_id, "openid", "full_access")
            print(f"[OK] Collaborator added - user can edit document")
        except Exception as e:
            print(f"[WARN] Add collaborator failed: {e}")
    else:
        print("[SKIP] No collaborator ID configured")

    # 保存结果
    doc_info = {
        "document_id": doc_id,
        "document_url": f"{config.get('FEISHU_WEB_DOMAIN', 'https://feishu.cn')}/docx/{doc_id}",
        "title": title,
        "created_at": datetime.now().isoformat(),
        "creator_type": "tenant"
    }

    doc_info_file = output_dir / "doc_info.json"
    with open(doc_info_file, 'w', encoding='utf-8') as f:
        json.dump(doc_info, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 70)
    print("Document Created Successfully!")
    print("=" * 70)
    print(f"Document ID: {doc_id}")
    print(f"Document URL: {doc_info['document_url']}")
    print(f"Output: {doc_info_file}")
    print()


if __name__ == "__main__":
    main()
