#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feishu Document Creator - 统一文档创建入口
支持云盘和知识库两种方式
"""

import json
import requests
import urllib.parse
from pathlib import Path
from typing import Dict, Optional


def load_config():
    """加载飞书配置"""
    import os
    config = {}
    # 非敏感配置仍从文件读取
    config_path = Path.home() / '.claude' / 'feishu-config.env'
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    k = key.strip()
                    if k not in ('FEISHU_APP_ID', 'FEISHU_APP_SECRET'):
                        config[k] = value.strip().strip('"\'')
    # 凭据只从系统环境变量读取
    config['FEISHU_APP_ID'] = os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_ID', '')
    config['FEISHU_APP_SECRET'] = os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_SECRET', '')
    return config


def get_access_token(config: Dict) -> str:
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
    raise Exception(f"获取token失败: {result}")


def add_permission(token: str, config: Dict, document_id: str):
    """添加协作者权限"""
    collaborator_id = config.get('FEISHU_AUTO_COLLABORATOR_ID')
    if not collaborator_id:
        return
    
    params = urllib.parse.urlencode({"type": "docx"})
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/drive/v1/permissions/{document_id}/members?{params}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "member_id": collaborator_id,
        "member_type": "openid",
        "perm": "full_access"
    }
    requests.post(url, json=payload, headers=headers)


def create_drive_doc(
    title: str,
    content: str,
    folder_token: Optional[str] = None
) -> Dict:
    """
    创建云盘文档
    
    Args:
        title: 文档标题
        content: Markdown 内容
        folder_token: 云盘文件夹token（默认使用配置）
    
    Returns:
        {"document_id": "...", "url": "...", "title": "..."}
    """
    config = load_config()
    token = get_access_token(config)
    
    # 使用默认文件夹
    if not folder_token:
        folder_token = config.get('FEISHU_DRIVE_FOLDER_TOKEN', 'DYPXf8ZktlOCIXdmGq3cfjevn2F')
    
    # 创建文档
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "title": title,
        "folder_token": folder_token
    }
    
    response = requests.post(url, json=payload, headers=headers)
    result = response.json()
    
    if result.get("code") != 0:
        raise Exception(f"创建文档失败: {result}")
    
    document_id = result["data"]["document"]["document_id"]
    
    # 添加权限
    add_permission(token, config, document_id)
    
    # 写入内容（使用 feishu-doc-orchestrator 的 parser）
    _write_content(token, config, document_id, content)
    
    return {
        "document_id": document_id,
        "url": f"https://feishu.cn/docx/{document_id}",
        "title": title
    }


def create_wiki_doc(
    title: str,
    content: str,
    parent_node_token: Optional[str] = None
) -> Dict:
    """
    创建知识库文档
    
    Args:
        title: 文档标题
        content: Markdown 内容
        parent_node_token: 父节点token（默认使用配置）
    
    Returns:
        {"node_token": "...", "obj_token": "...", "url": "...", "title": "..."}
    """
    config = load_config()
    token = get_access_token(config)
    
    # 使用默认父节点
    if not parent_node_token:
        parent_node_token = config.get('FEISHU_PARENT_DAILY_REPORT', 'LmZ6wKwTViA4bSkVSYfcJGFcnRf')
    
    space_id = config.get('FEISHU_WIKI_SPACE_ID', '7313882962775556100')
    
    # 创建Wiki节点
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/wiki/v2/spaces/{space_id}/nodes"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "obj_type": "docx",
        "node_type": "origin",
        "parent_node_token": parent_node_token,
        "title": title
    }
    
    response = requests.post(url, json=payload, headers=headers)
    result = response.json()
    
    if result.get("code") != 0:
        raise Exception(f"创建Wiki节点失败: {result}")
    
    node_token = result['data']['node']['node_token']
    obj_token = result['data']['node']['obj_token']
    
    # 添加权限
    add_permission(token, config, obj_token)
    
    # 写入内容
    _write_content(token, config, obj_token, content)
    
    return {
        "node_token": node_token,
        "obj_token": obj_token,
        "url": f"https://uniquecapital.feishu.cn/wiki/{node_token}",
        "title": title
    }


def _write_content(token: str, config: Dict, document_id: str, content: str):
    """
    写入文档内容
    使用 feishu_doc.write 工具
    """
    # 简单实现：直接调用 feishu_doc API
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents/{document_id}/content"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 将 Markdown 转为纯文本块
    # 这里简化处理，实际应该使用 feishu-doc-orchestrator 的 parser
    # 但为了独立性，先实现基础版本
    
    # 分段处理
    blocks = []
    lines = content.split('\n')
    current_text = []
    
    for line in lines:
        if line.startswith('#'):
            # 先提交之前的文本
            if current_text:
                text_content = '\n'.join(current_text).strip()
                if text_content:
                    blocks.append({
                        "block_type": 2,
                        "text": {
                            "elements": [{"text_run": {"content": text_content}}],
                            "style": {}
                        }
                    })
                current_text = []
            
            # 处理标题
            level = len(line) - len(line.lstrip('#'))
            heading_text = line.lstrip('#').strip()
            if heading_text:
                blocks.append({
                    "block_type": 2 + min(level, 9),  # heading1-9
                    f"heading{min(level, 9)}": {
                        "elements": [{"text_run": {"content": heading_text}}],
                        "style": {}
                    }
                })
        else:
            current_text.append(line)
    
    # 提交剩余的文本
    if current_text:
        text_content = '\n'.join(current_text).strip()
        if text_content:
            blocks.append({
                "block_type": 2,
                "text": {
                    "elements": [{"text_run": {"content": text_content}}],
                    "style": {}
                }
            })
    
    # 批量添加块
    if blocks:
        batch_size = 50
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i:i+batch_size]
            add_url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/children"
            payload = {
                "children": batch,
                "index": -1
            }
            requests.post(add_url, json=payload, headers=headers)


# 便捷函数
def create_doc(title: str, content: str, doc_type: str = "drive", **kwargs) -> Dict:
    """
    统一创建文档入口
    
    Args:
        title: 文档标题
        content: Markdown 内容
        doc_type: "drive" 或 "wiki"
        **kwargs: 额外参数
    
    Returns:
        文档信息字典
    """
    if doc_type == "drive":
        return create_drive_doc(title, content, **kwargs)
    elif doc_type == "wiki":
        return create_wiki_doc(title, content, **kwargs)
    else:
        raise ValueError(f"不支持的文档类型: {doc_type}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 4:
        print("用法: python feishu_doc_creator.py <drive|wiki> <标题> <md文件>")
        sys.exit(1)
    
    doc_type = sys.argv[1]
    title = sys.argv[2]
    md_file = sys.argv[3]
    
    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    result = create_doc(title, content, doc_type)
    print(json.dumps(result, ensure_ascii=False, indent=2))
