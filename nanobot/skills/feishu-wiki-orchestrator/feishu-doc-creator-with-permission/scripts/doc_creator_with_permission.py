#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档创建器+权限管理器 - 合并子技能
在飞书创建文档并自动完成权限管理
输出：doc_with_permission.json
"""

import sys
import json
import urllib.parse
import time
from pathlib import Path
from datetime import datetime
import requests

# 添加 feishu_auth 路径
AUTH_SCRIPT_DIR = Path(__file__).parent.parent.parent / "feishu-doc-creator" / "scripts"
if str(AUTH_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(AUTH_SCRIPT_DIR))


def load_config():
    """加载飞书配置（凭据从系统环境变量读取）"""
    import os
    possible_paths = [
        Path.home() / '.nanobot' / '.env',
        Path(__file__).parent.parent.parent.parent / "feishu-config.env",
        Path(".claude/feishu-config.env"),
        Path("../feishu-config.env"),
        Path("../../feishu-config.env"),
    ]
    
    config = {}
    for p in possible_paths:
        if p.exists():
            with open(p, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        k = key.strip()
                        if k not in ('FEISHU_APP_ID', 'FEISHU_APP_SECRET'):
                            config[k] = value.strip().strip('"\'')
            break
    
    config['FEISHU_APP_ID'] = os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_ID', '')
    config['FEISHU_APP_SECRET'] = os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_SECRET', '')
    return config


def get_access_token(config, use_user_token=False):
    """获取访问令牌"""
    if use_user_token:
        # 从文件读取 user_access_token
        token_path = Path(__file__).parent.parent.parent.parent / "feishu-token.json"
        if token_path.exists():
            with open(token_path, 'r', encoding='utf-8') as f:
                token_data = json.load(f)
                # 支持 access_token 和 user_access_token 两种格式
                return token_data.get("user_access_token") or token_data.get("access_token")
        return None
    else:
        # 获取 tenant_access_token
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
            raise Exception(f"获取 tenant_access_token 失败: {result}")


def create_document(token, config, title):
    """创建飞书知识库文档 - 使用 wiki API 在知识库中创建"""
    # 获取知识库配置（默认空间ID和父节点token）
    space_id = config.get('FEISHU_WIKI_SPACE_ID', '7313882962775556100')
    parent_node_token = config.get('FEISHU_WIKI_PARENT_NODE', 'Uqsqwoug5iYca3koiAQcUaEqnOf')
    
    # 使用 wiki API 在知识库创建文档
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/wiki/v2/spaces/{space_id}/nodes"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "title": title,
        "parent_node_token": parent_node_token,
        "obj_type": "docx",
        "node_type": "origin"
    }

    response = requests.post(url, json=payload, headers=headers)
    
    # 调试：打印原始响应
    print(f"     响应状态: {response.status_code}")
    
    try:
        result = response.json()
    except json.JSONDecodeError as e:
        raise Exception(f"JSON解析失败: {e}, 原始响应: {response.text[:500]}")

    if result.get("code") == 0:
        doc_id = result["data"]["node"]["obj_token"]
        node_token = result["data"]["node"]["node_token"]
        print(f"     文档ID: {doc_id}")
        print(f"     节点Token: {node_token}")
        return doc_id, node_token
    else:
        raise Exception(f"创建知识库文档失败: {result}")


def add_permission_member(token, config, document_id, user_id, user_type, perm):
    """添加协作者权限 - 必须使用 tenant_access_token"""
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
    """主函数 - 命令行入口"""
    # 解析参数
    title = "未命名文档"
    output_dir = Path("output")

    if len(sys.argv) >= 2:
        title = sys.argv[1]

    if len(sys.argv) >= 3:
        output_dir = Path(sys.argv[2])

    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载配置
    config = load_config()
    if not config:
        print("[feishu-doc-creator-with-permission] Error: Unable to load config")
        sys.exit(1)

    print("=" * 70)
    print("知识库文档创建 + 权限管理（原子操作）")
    print("=" * 70)
    print(f"文档标题: {title}")
    print(f"创建位置: 知识库")
    print()

    # 权限配置
    collaborator_id = config.get('FEISHU_AUTO_COLLABORATOR_ID')
    collaborator_type = config.get('FEISHU_AUTO_COLLABORATOR_TYPE', 'openid')
    collaborator_perm = config.get('FEISHU_AUTO_COLLABORATOR_PERM', 'full_access')

    # 结果数据
    result = {
        "title": title,
        "created_at": datetime.now().isoformat(),
        "permission": {
            "collaborator_added": False,
            "user_has_full_control": False,
            "collaborator_id": collaborator_id
        },
        "errors": []
    }

    # ========== 第一步：创建文档 ==========
    print("[步骤 1/2] 创建文档 (tenant_access_token)...")
    try:
        token = get_access_token(config, use_user_token=False)
        doc_id, node_token = create_document(token, config, title)
        result["document_id"] = doc_id
        result["node_token"] = node_token
        result["document_url"] = f"{config.get('FEISHU_WEB_DOMAIN', 'https://feishu.cn')}/docx/{doc_id}"
        print(f"[OK] 知识库文档创建成功")
        print(f"     文档ID: {doc_id}")
    except Exception as e:
        error_msg = str(e)
        result["errors"].append(f"创建文档失败: {error_msg}")
        print(f"[FAIL] 创建文档失败: {error_msg}")
        # 保存失败结果并退出
        result_file = output_dir / "doc_with_permission.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        sys.exit(1)

    # ========== 第二步：添加协作者权限 ==========
    # 注：由于云盘/知识库路径配置，创建者自动拥有管理权限，无需所有权转移
    print("\n[步骤 2/2] 添加协作者权限 (tenant_access_token)...")
    if collaborator_id:
        try:
            add_permission_member(token, config, doc_id, collaborator_id, collaborator_type, collaborator_perm)
            result["permission"]["collaborator_added"] = True
            result["permission"]["user_has_full_control"] = True
            print(f"[OK] 协作者权限添加成功")
            print(f"     协作者ID: {collaborator_id}")
            print(f"[INFO] 用户已获得完全控制权（可编辑+可删除）")
        except Exception as e:
            error_msg = str(e)
            result["errors"].append(f"添加协作者失败: {error_msg}")
            print(f"[FAIL] 添加协作者失败: {error_msg}")
            print("[WARN] 用户可能无法编辑文档")
    else:
        print("[SKIP] 未配置协作者 ID，跳过")
        result["errors"].append("未配置协作者 ID，跳过权限添加")

    # 保存结果
    result_file = output_dir / "doc_with_permission.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 打印摘要
    print()
    print("=" * 70)
    print("操作完成")
    print("=" * 70)
    print(f"文档URL: {result['document_url']}")
    print(f"协作者添加: {result['permission']['collaborator_added']}")
    print(f"用户完全控制: {result['permission']['user_has_full_control']}")
    print(f"用户完全控制: {result['permission']['user_has_full_control']}")
    print(f"\n输出文件: {result_file}")
    print(f"\n[OUTPUT] {result_file}")


if __name__ == "__main__":
    main()
