#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
早晚报飞书文档生成器
使用 feishu-doc-orchestrator 技能将MD转换为完整格式的飞书文档

配置文件: ~/.nanobot/.env (统一配置)

用法:
    python create_feishu_doc.py <md_file> <title>
    python create_feishu_doc.py <md_file> <title> --type other

示例:
    python create_feishu_doc.py HiperOneAI早报_2026-02-08_V5.md "📰 HiperOneAI早报 | 2026-02-08"
"""

import os
import sys
import json
import time
import argparse
import urllib.parse
from pathlib import Path
import requests


def _inject_feishu_credentials(config: dict) -> dict:
    """从系统环境变量注入飞书凭据"""
    config['FEISHU_APP_ID'] = os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_ID', '')
    config['FEISHU_APP_SECRET'] = os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_SECRET', '')
    return config


def load_config():
    """加载飞书配置（非敏感配置从 JSON/env 文件读取，凭据从系统环境变量读取）"""
    json_config_paths = [
        Path(__file__).parent.parent.parent.parent / "config" / "feishu.json",
        Path.home() / '.nanobot' / 'workspace' / 'config' / 'feishu.json',
    ]
    
    for json_path in json_config_paths:
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    json_config = json.load(f)
                config = {}
                if 'api' in json_config and 'domain' in json_config['api']:
                    config['FEISHU_API_DOMAIN'] = json_config['api']['domain']
                if 'app' in json_config and 'autoCollaboratorId' in json_config['app']:
                    config['FEISHU_AUTO_COLLABORATOR_ID'] = json_config['app']['autoCollaboratorId']
                if 'wiki' in json_config:
                    if 'spaceId' in json_config['wiki']:
                        config['FEISHU_WIKI_SPACE_ID'] = json_config['wiki']['spaceId']
                    if 'parentNodes' in json_config['wiki']:
                        nodes = json_config['wiki']['parentNodes']
                        if 'dailyReport' in nodes:
                            config['FEISHU_PARENT_DAILY_REPORT'] = nodes['dailyReport']
                        if 'other' in nodes:
                            config['FEISHU_PARENT_OTHER'] = nodes['other']
                        if 'deepObservation' in nodes:
                            config['FEISHU_PARENT_DEEP_OBSERVATION'] = nodes['deepObservation']
                if 'drive' in json_config and 'defaultFolder' in json_config['drive']:
                    config['FEISHU_DEFAULT_FOLDER'] = json_config['drive']['defaultFolder']
                    config['FEISHU_DRIVE_FOLDER_TOKEN'] = json_config['drive']['defaultFolder']
                return _inject_feishu_credentials(config)
            except Exception as e:
                print(f"[Warning] 读取 JSON 配置失败: {e}, 尝试回退到旧配置")
    
    # 回退：从 .env 读取非敏感配置
    config = {}
    config_paths = [
        Path.home() / '.nanobot' / '.env',
        Path.home() / '.claude' / 'feishu-config.env',
    ]
    for p in config_paths:
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
    
    return _inject_feishu_credentials(config)


def get_parent_node(config, doc_type: str) -> str:
    """根据文档类型获取父节点"""
    if doc_type == "daily_report":
        return config.get('FEISHU_PARENT_DAILY_REPORT', config.get('FEISHU_DEFAULT_PARENT'))
    else:
        return config.get('FEISHU_PARENT_OTHER', config.get('FEISHU_DEFAULT_PARENT'))


def get_token(config):
    """获取 tenant_access_token"""
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        'app_id': config['FEISHU_APP_ID'],
        'app_secret': config['FEISHU_APP_SECRET']
    }
    response = requests.post(url, json=payload, timeout=10)
    result = response.json()
    
    if result.get('code') != 0:
        raise Exception(f"获取token失败: {result}")
    
    return result['tenant_access_token']


def parse_markdown(md_file: str, output_dir: str):
    """使用 feishu-md-parser 解析 Markdown"""
    import subprocess
    
    parser_script = Path.home() / '.agents/skills/feishu-doc-orchestrator/feishu-md-parser/scripts/md_parser.py'
    
    result = subprocess.run(
        [sys.executable, str(parser_script), md_file, output_dir],
        capture_output=True,
        text=True,
        timeout=60
    )
    
    if result.returncode != 0:
        raise Exception(f"MD解析失败: {result.stderr}")
    
    blocks_file = Path(output_dir) / 'blocks.json'
    with open(blocks_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    return data['blocks'], data.get('metadata', {})


def create_wiki_node(token: str, config: dict, title: str, doc_type: str = "daily_report"):
    """在Wiki知识库中创建节点"""
    parent_node = get_parent_node(config, doc_type)
    space_id = config.get('FEISHU_WIKI_SPACE_ID')
    
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/wiki/v2/spaces/{space_id}/nodes"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    payload = {
        "obj_type": "docx",
        "node_type": "origin",
        "parent_node_token": parent_node,
        "title": title
    }
    
    response = requests.post(url, json=payload, headers=headers, timeout=15)
    result = response.json()
    
    if result.get('code') != 0:
        raise Exception(f"创建Wiki节点失败: {result}")
    
    return {
        "node_token": result['data']['node']['node_token'],
        "obj_token": result['data']['node']['obj_token']
    }


def add_permission(token: str, config: dict, doc_id: str):
    """添加协作者权限"""
    params = urllib.parse.urlencode({'type': 'docx'})
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/drive/v1/permissions/{doc_id}/members?{params}"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    payload = {
        'member_type': 'openid',
        'member_id': config['FEISHU_AUTO_COLLABORATOR_ID'],
        'perm': 'full_access'
    }
    
    response = requests.post(url, json=payload, headers=headers, timeout=15)
    result = response.json()
    
    return result.get('code') == 0


def clean_cell_content(content: str) -> str:
    """清理单元格内容"""
    if not content:
        return ""
    content = str(content).strip()
    content = content.replace('\u200b', '')
    content = content.replace('\u200c', '')
    content = content.replace('\u200d', '')
    content = content.replace('\ufeff', '')
    import re
    content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
    if '\n' in content:
        content = content.split('\n')[0].strip()
    return content


def create_table_with_style(token: str, config: dict, doc_id: str, rows_data: list):
    """创建表格并填充内容"""
    row_size = len(rows_data)
    col_size = len(rows_data[0]) if rows_data else 0
    
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    payload = {
        'children': [{
            'block_type': 31,
            'table': {
                'property': {
                    'row_size': row_size,
                    'column_size': col_size,
                    'header_row': True
                }
            }
        }],
        'index': -1
    }
    
    response = requests.post(url, json=payload, headers=headers)
    result = response.json()
    
    if result.get('code') != 0:
        raise Exception(f"创建表格失败: {result}")
    
    table_id = result['data']['children'][0]['block_id']
    cell_ids = result['data']['children'][0].get('children', [])
    
    # 准备所有单元格数据（跳过空内容）
    cell_tasks = []
    for row_idx, row in enumerate(rows_data):
        for col_idx, cell_content in enumerate(row):
            cell_index = row_idx * col_size + col_idx
            if cell_index < len(cell_ids):
                cleaned = clean_cell_content(cell_content)
                if cleaned:  # 只处理非空单元格
                    cell_tasks.append({
                        'cell_id': cell_ids[cell_index],
                        'content': cleaned,
                        'row': row_idx,
                        'col': col_idx
                    })
    
    # 顺序填充单元格（飞书API不支持并发写入同一文档）
    filled = 0
    errors = 0
    
    for i, task in enumerate(cell_tasks):
        cell_url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents/{doc_id}/blocks/{task['cell_id']}/children"
        cell_payload = {
            'children': [{
                'block_type': 2,
                'text': {
                    'elements': [{'text_run': {'content': task['content']}}],
                    'style': {}
                }
            }],
            'index': -1
        }
        
        try:
            resp = requests.post(cell_url, json=cell_payload, headers=headers, timeout=10)
            if resp.json().get('code') == 0:
                filled += 1
            else:
                errors += 1
        except Exception:
            errors += 1
        
        # 最小延迟避免触发限流
        if i < len(cell_tasks) - 1:
            time.sleep(0.03)  # 30ms延迟
    
    # 统计信息
    empty_cells = len(cell_ids) - len(cell_tasks)
    if empty_cells > 0:
        print(f" ℹ️ 跳过{empty_cells}个空单元格", end='', flush=True)
    if errors > 0:
        print(f" ⚠️ {errors}个单元格失败", end='', flush=True)
    
    return table_id
    
    return table_id


def add_blocks(token: str, config: dict, doc_id: str, blocks: list):
    """分批添加块到文档"""
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    # 有效块类型 (飞书 Docx API 支持的 block_type)
    # 2=text, 3-11=heading1-9, 12=bullet, 13=ordered, 14=code, 15=quote
    # 17=todo, 19=callout, 22=divider, 27=image, 31=table
    valid_block_types = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 19, 22, 27]
    
    batch_size = 10
    added = 0
    errors = 0
    table_count = 0
    
    for i in range(0, len(blocks), batch_size):
        batch = blocks[i:i+batch_size]
        normal_blocks = []
        
        for block in batch:
            # 表格特殊处理
            if block.get('type') == 'table':
                try:
                    print(f"  📊 创建表格 {table_count + 1} ({len(block['data'])} 行)...", end='', flush=True)
                    create_table_with_style(token, config, doc_id, block['data'])
                    table_count += 1
                    added += 1
                    print(" ✅")
                except Exception as e:
                    errors += 1
                    print(f" ❌ {str(e)[:50]}")
                continue
            
            # 检查 block_type 是否在有效列表中
            if block.get('block_type') in valid_block_types:
                normal_blocks.append(block)
        
        if not normal_blocks:
            continue
        
        url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children"
        payload = {'children': normal_blocks, 'index': -1}
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            result = response.json()
            if result.get('code') == 0:
                added += len(normal_blocks)
            else:
                print(f"  ⚠️  批量添加失败: {result.get('msg', '未知错误')}")
                errors += 1
        except Exception as e:
            print(f"  ⚠️  批量添加异常: {str(e)[:50]}")
            errors += 1
        
        time.sleep(0.3)  # 避免限流
    
    return added, errors, table_count


def main():
    parser = argparse.ArgumentParser(description='生成早晚报飞书文档')
    parser.add_argument('md_file', help='Markdown 文件路径')
    parser.add_argument('title', help='文档标题')
    parser.add_argument('--type', default='daily_report', choices=['daily_report', 'other'], 
                        help='文档类型: daily_report=AI日报存档, other=我是HiperOne')
    parser.add_argument('--output-dir', default='/tmp/daily_report_workflow', help='临时输出目录')
    
    args = parser.parse_args()
    
    # 确保输出目录存在
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("🦞 HiperOne早晚报飞书文档生成器")
    print("=" * 50)
    
    # 1. 加载配置
    print("\n[1/5] 加载配置...")
    config = load_config()
    token = get_token(config)
    print("  ✅ Token 获取成功")
    print(f"  📁 目标父节点: {'AI日报存档' if args.type == 'daily_report' else '我是HiperOne'}")
    
    # 2. 解析 Markdown
    print("\n[2/5] 解析 Markdown...")
    blocks, metadata = parse_markdown(args.md_file, str(output_dir))
    print(f"  ✅ 解析完成: {metadata.get('total_blocks', len(blocks))} 个块")
    
    # 3. 创建Wiki节点
    print("\n[3/5] 创建飞书Wiki节点...")
    wiki_info = create_wiki_node(token, config, args.title, args.type)
    doc_id = wiki_info['obj_token']
    node_token = wiki_info['node_token']
    wiki_url = f"https://uniquecapital.feishu.cn/wiki/{node_token}"
    print(f"  ✅ 节点创建成功")
    
    # 4. 添加权限
    print("\n[4/5] 添加协作者权限...")
    perm_ok = add_permission(token, config, doc_id)
    print(f"  {'✅' if perm_ok else '⚠️'} 权限{'添加成功' if perm_ok else '可能失败'}")
    
    # 5. 添加内容块
    print("\n[5/5] 添加内容块...")
    added, errors, table_count = add_blocks(token, config, doc_id, blocks)
    print(f"  ✅ 添加完成: {added} 个块 ({table_count} 个表格), {errors} 个错误")
    
    # 输出结果
    print("\n" + "=" * 50)
    print("📄 文档链接:", wiki_url)
    print("=" * 50)
    
    # 保存结果
    result = {
        'node_token': node_token,
        'document_id': doc_id,
        'document_url': wiki_url,
        'title': args.title,
        'doc_type': args.type,
        'blocks_added': added,
        'tables_added': table_count,
        'errors': errors,
        'metadata': metadata
    }
    
    result_file = output_dir / 'result.json'
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # 返回结果供程序调用
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == '__main__':
    main()
