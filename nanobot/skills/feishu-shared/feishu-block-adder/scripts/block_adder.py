#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
块添加器 - 子技能3
将解析后的块数据添加到飞书文档
输出：add_result.json
"""

import sys
import json
import time
import re
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
        'FEISHU_AUTO_COLLABORATOR_ID': os.environ.get('FEISHU_AUTO_COLLABORATOR_ID', ''),
    }
    if not config['FEISHU_APP_ID'] or not config['FEISHU_APP_SECRET']:
        raise Exception("缺少飞书凭据，请设置环境变量 NANOBOT_CHANNELS__FEISHU__APP_ID / NANOBOT_CHANNELS__FEISHU__APP_SECRET")
    return config


def get_access_token(config, use_user_token=False):
    """获取访问令牌"""
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


def clean_cell_content(content):
    """清理单元格内容"""
    if not content:
        return ""
    content = str(content).strip()
    content = content.replace('\u200b', '')
    content = content.replace('\u200c', '')
    content = content.replace('\u200d', '')
    content = content.replace('\ufeff', '')
    content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
    if '\n' in content:
        content = content.split('\n')[0].strip()
    return content


def create_table_with_style(token, config, document_id, rows_data):
    """创建表格并填充内容"""
    row_size = len(rows_data)
    col_size = len(rows_data[0]) if rows_data else 0

    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/children"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "children": [{
            "block_type": 31,
            "table": {
                "property": {
                    "row_size": row_size,
                    "column_size": col_size,
                    "header_row": True
                }
            }
        }],
        "index": -1
    }

    response = requests.post(url, json=payload, headers=headers)
    result = response.json()

    if result.get("code") != 0:
        raise Exception(f"创建表格失败: {result}")

    table_id = result["data"]["children"][0]["block_id"]
    cell_ids = result["data"]["children"][0].get("children", [])

    # 填充单元格内容
    for row_idx, row in enumerate(rows_data):
        for col_idx, cell_content in enumerate(row):
            cell_index = row_idx * col_size + col_idx
            if cell_index < len(cell_ids):
                cell_id = cell_ids[cell_index]
                cell_url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents/{document_id}/blocks/{cell_id}/children"

                cell_content = clean_cell_content(cell_content)
                cell_payload = {
                    "children": [{
                        "block_type": 2,
                        "text": {
                            "elements": [{"text_run": {"content": cell_content}}],
                            "style": {}
                        }
                    }],
                    "index": -1
                }

                for attempt in range(3):
                    try:
                        resp = requests.post(cell_url, json=cell_payload, headers=headers, timeout=10)
                        if resp.json().get("code") == 0:
                            break
                    except:
                        pass
                    time.sleep(0.1)
        time.sleep(0.05)

    return table_id


def create_callout_with_children(token, config, document_id, callout_style, callout_content):
    """创建高亮块

    ⚠️ 关键修复：callout 块的颜色字段必须直接在 callout 对象下，不能嵌套在 style 中

    错误格式示例：
        "callout": {
            "elements": [...],
            "style": {"emoji_id": "...", "background_color": 1}  # ❌ 错误
        }

    正确格式示例：
        "callout": {
            "elements": [...],
            "emoji_id": "...",          # ✓ 直接在 callout 下
            "background_color": 1        # ✓ 直接在 callout 下
        }

    调试经验：
        - 如果 API 返回的 callout 只有 emoji_id，说明格式错误
        - 验证方法：检查响应 data.children[0].callout 是否包含颜色字段
    """
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/children"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 使用 **callout_style 展开操作符，将样式字段直接展开到 callout 对象下
    payload = {
        "children": [{
            "block_type": 19,
            "callout": {
                "elements": [{"text_run": {"content": callout_content}}],
                **callout_style  # 关键：展开样式字段到 callout 对象下，不要嵌套在 style 中
            }
        }],
        "index": -1
    }

    response = requests.post(url, json=payload, headers=headers)
    result = response.json()

    if result.get("code") != 0:
        raise Exception(f"创建 callout 块失败: {result}")

    # 验证：检查返回的 callout 是否包含颜色字段
    returned_callout = result["data"]["children"][0].get("callout", {})
    if "background_color" not in returned_callout and "border_color" not in returned_callout:
        print(f"[WARN] Callout 创建成功但可能缺少颜色字段，返回: {returned_callout}")

    return result["data"]["children"][0]["block_id"]


def add_children_to_block(token, config, document_id, parent_block_id, children):
    """添加子块到指定块"""
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "children": children,
        "index": -1
    }

    response = requests.post(url, json=payload, headers=headers)
    result = response.json()

    if result.get("code") != 0:
        raise Exception(f"添加子块失败: {result}")

    return result


def main():
    """主函数"""
    if len(sys.argv) < 3:
        print("Usage: python block_adder.py <blocks.json> <doc_info.json> [output_dir]")
        sys.exit(1)

    blocks_file = Path(sys.argv[1])
    doc_info_file = Path(sys.argv[2])

    if len(sys.argv) >= 4:
        output_dir = Path(sys.argv[3])
    else:
        output_dir = Path("output")

    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载块数据
    print(f"[feishu-block-adder] Loading blocks from: {blocks_file}")
    with open(blocks_file, 'r', encoding='utf-8') as f:
        blocks_data = json.load(f)
    blocks = blocks_data["blocks"]
    metadata = blocks_data.get("metadata", {})

    # 加载文档信息
    print(f"[feishu-block-adder] Loading doc info from: {doc_info_file}")
    with open(doc_info_file, 'r', encoding='utf-8') as f:
        doc_info = json.load(f)
    doc_id = doc_info["document_id"]

    # 加载配置
    config = load_config()
    token = get_access_token(config, use_user_token=False)

    print(f"[feishu-block-adder] Document ID: {doc_id}")
    print(f"[feishu-block-adder] Total blocks: {len(blocks)}")

    # 分批处理
    batch_size = 50  # 优化：从20增加到50，减少API调用次数，避免乱序
    table_count = 0
    callout_count = 0
    regular_blocks = 0
    start_time = time.time()

    for i in range(0, len(blocks), batch_size):
        batch = blocks[i:i+batch_size]
        valid_blocks = []

        for block in batch:
            if block.get("type") == "table":
                try:
                    print(f"  Creating table {table_count + 1} with {len(block['data'])} rows")
                    create_table_with_style(token, config, doc_id, block["data"])
                    table_count += 1
                    print(f"  [OK] Table {table_count} created")
                except Exception as e:
                    print(f"  [FAIL] Table failed: {str(e)[:80]}")
            else:
                block_copy = {k: v for k, v in block.items() if k != "type"}
                # 支持的块类型：25 种飞书文档块
                # 文本块：text (2), heading1-9 (3-11)
                # 列表：bullet (12), ordered (13), todo (17)
                # 特殊：code (14), quote (15), callout (19), divider (22)
                # 媒体：image (27)
                # 高级：quote_container (34), task (35)
                # callout (19) 现在直接包含 elements 和 style，可以批量添加
                if block_copy.get("block_type") in [
                    2, 3, 4, 5, 6, 7, 8, 9, 10, 11,  # text, heading1-9
                    12, 13, 17,                             # bullet, ordered, todo
                    14, 15, 19, 22,                         # code, quote, callout, divider
                    27,                                     # image
                    34, 35                                  # quote_container, task
                ]:
                    valid_blocks.append(block_copy)
                    if block_copy.get("block_type") == 19:
                        callout_count += 1
                    regular_blocks += 1

        if valid_blocks:
            try:
                add_children_to_block(token, config, doc_id, doc_id, valid_blocks)
            except Exception as e:
                print(f"  [FAIL] Batch failed: {str(e)[:80]}")

        print(f"Processed {min(i+batch_size, len(blocks))}/{len(blocks)} blocks")
        time.sleep(0.5)  # 优化：从0.2s增加到0.5s，给服务器处理时间，避免乱序

    duration = time.time() - start_time

    # 保存结果
    result = {
        "success": True,
        "document_id": doc_id,
        "total_blocks": len(blocks),
        "tables_created": table_count,
        "callouts_created": callout_count,
        "regular_blocks": regular_blocks,
        "batches": (len(blocks) + batch_size - 1) // batch_size,
        "duration_seconds": round(duration, 2),
        "completed_at": datetime.now().isoformat()
    }

    result_file = output_dir / "add_result.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[feishu-block-adder] Completed in {duration:.2f}s")
    print(f"[feishu-block-adder] Tables created: {table_count}")
    print(f"[feishu-block-adder] Callouts created: {callout_count}")
    print(f"[feishu-block-adder] Regular blocks: {regular_blocks}")
    print(f"[feishu-block-adder] Output: {result_file}")
    print(f"\n[OUTPUT] {result_file}")


if __name__ == "__main__":
    main()
