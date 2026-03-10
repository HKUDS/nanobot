#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown 解析器 - 子技能1（增强版）
将 Markdown 文件解析为飞书文档块格式
支持 25 种飞书文档块类型
输出：blocks.json
"""

import sys
import json
import re
import time
from pathlib import Path
from typing import List, Dict, Any


def clean_cell_content(content: str) -> str:
    """彻底清理单元格内容，去除零宽字符等"""
    if not content:
        return ""

    content = str(content).strip()

    # 移除零宽字符
    content = content.replace('\u200b', '')  # 零宽空格
    content = content.replace('\u200c', '')  # 零宽非连字符
    content = content.replace('\u200d', '')  # 零宽连字符
    content = content.replace('\ufeff', '')  # 零宽非断空格

    # 移除 ** 粗体标记
    content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)

    # 如果有换行，只取第一行
    if '\n' in content:
        content = content.split('\n')[0].strip()

    return content


def make_text_run(text: str, bold: bool = False) -> Dict[str, Any]:
    """创建文本运行元素 - 自动清理零宽字符"""
    # 清理零宽字符
    text = text.replace('\u200b', '')
    text = text.replace('\u200c', '')
    text = text.replace('\u200d', '')
    text = text.replace('\ufeff', '')
    result = {"text_run": {"content": text}}
    if bold:
        result["text_run"]["text_element_style"] = {"bold": True}
    return result


def parse_markdown_text(content: str) -> List[Dict[str, Any]]:
    """解析 Markdown 文本，转换 **粗体** 为飞书样式"""
    if not content:
        return [{"text_run": {"content": ""}}]

    elements = []
    parts = content.split('**')

    for idx, part in enumerate(parts):
        if part:
            is_bold = (idx % 2 == 1)
            part = part.replace('*', '').strip()
            if part:
                elements.append(make_text_run(part, bold=is_bold))

    return elements if elements else [make_text_run(content)]


def get_callout_style(style_name: str) -> Dict[str, Any]:
    """
    获取 callout 样式配置

    支持 6 种样式：info, tip, warning, success, note, important

    颜色值必须是数字（根据飞书 API 规范）：
    - background_color: 1-15 (浅色系1-7, 中色系8-14, 浅灰15)
    - border_color: 1-7 (红橙黄绿蓝紫灰)
    - text_color: 1-7, 15 (红橙黄绿蓝紫灰, 白色15)

    ⚠️ 重要：返回的字段必须直接展开到 callout 对象下，不能嵌套在 style 中！
    错误格式：callout.style.{emoji_id, background_color, ...}
    正确格式：callout.{emoji_id, background_color, ...}

    调试经验：
    - 如果 API 返回的 callout 只有 emoji_id 而没有颜色字段，说明格式错误
    - 测试 URL 查看响应：https://my.feishu.cn/docx/{doc_id}
    """
    styles = {
        "info": {"emoji_id": "information_source", "background_color": 5, "border_color": 5},  # 蓝色
        "tip": {"emoji_id": "bulb", "background_color": 3, "border_color": 3, "text_color": 3},  # 黄色
        "warning": {"emoji_id": "warning", "background_color": 1, "border_color": 1, "text_color": 1},  # 红色
        "success": {"emoji_id": "white_check_mark", "background_color": 4, "border_color": 4, "text_color": 4},  # 绿色
        "note": {"emoji_id": "pushpin", "background_color": 7, "border_color": 7},  # 灰色
        "important": {"emoji_id": "fire", "background_color": 8, "border_color": 1, "text_color": 1},  # 橙红色
    }
    return styles.get(style_name.lower(), styles["info"])


def parse_markdown_to_blocks(markdown_text: str, include_first_title: bool = False) -> Dict[str, Any]:
    """
    将 Markdown 转换为飞书块
    支持 25 种飞书文档块类型

    返回格式：
    {
        "blocks": [...],
        "metadata": {...}
    }
    """
    lines = markdown_text.split('\n')
    blocks = []
    i = 0
    first_title_skipped = not include_first_title

    # 元数据统计
    metadata = {
        "heading_count": 0,
        "table_count": 0,
        "list_count": 0,
        "code_count": 0,
        "callout_count": 0,
        "todo_count": 0,
        "image_count": 0,
        "total_blocks": 0
    }

    # 状态变量
    in_callout_block = False
    callout_content = []
    callout_type = 'info'

    while i < len(lines):
        line = lines[i].rstrip()

        # ========== 处理 Callout 块 (:::type 语法) ==========
        if line.startswith(':::'):
            if not in_callout_block:
                # Callout 开始
                callout_type = line[3:].strip().lower()
                in_callout_block = True
                callout_content = []
            else:
                # Callout 结束，创建 Callout 块
                callout_text = '\n'.join(callout_content).strip()
                style = get_callout_style(callout_type)

                # ==================== 关键修复说明 ====================
                # Callout 块的颜色字段必须直接在 callout 对象下，不能嵌套在 style 中
                #
                # ❌ 错误格式（API 会忽略颜色字段）：
                # {
                #     "block_type": 19,
                #     "callout": {
                #         "elements": [...],
                #         "style": {  # 错误：嵌套在 style 中
                #             "emoji_id": "warning",
                #             "background_color": 1,
                #             "border_color": 1
                #         }
                #     }
                # }
                #
                # ✓ 正确格式（颜色字段直接在 callout 下）：
                # {
                #     "block_type": 19,
                #     "callout": {
                #         "elements": [...],
                #         "emoji_id": "warning",      # 直接在 callout 下
                #         "background_color": 1,      # 直接在 callout 下
                #         "border_color": 1           # 直接在 callout 下
                #     }
                # }
                #
                # 调试方法：
                # 1. 如果 API 返回的 callout 只有 emoji_id 而没有颜色，说明格式错误
                # 2. 使用测试脚本单独验证 callout 格式
                # =====================================================
                blocks.append({
                    "block_type": 19,
                    "callout": {
                        "elements": [{"text_run": {"content": callout_text}}],
                        **style  # 使用 Python 展开操作符，将 style 字段直接展开到 callout 对象下
                    }
                })
                metadata["callout_count"] += 1
                in_callout_block = False
            i += 1
            continue

        if in_callout_block:
            callout_content.append(line)
            i += 1
            continue

        if not line:
            i += 1
            continue

        # ========== 1. 标题 (heading1-9) ==========
        if line.startswith('#'):
            level_match = re.match(r'^(#{1,9})\s', line)
            if level_match:
                level = len(level_match.group(1))
                content = line.lstrip('#').strip()
                if first_title_skipped and level == 1:
                    first_title_skipped = False
                    i += 1
                    continue
                elements = parse_markdown_text(content)
                # 支持 heading1-9 (block_type 3-11)
                blocks.append({
                    "block_type": 2 + level,
                    f"heading{level}": {
                        "elements": elements,
                        "style": {}
                    }
                })
                metadata["heading_count"] += 1
                i += 1
                continue

        # ========== 2. 分割线 ==========
        if line.strip() == '---':
            blocks.append({"block_type": 22, "divider": {}})
            i += 1
            continue

        # ========== 3. 引用块 (quote) ==========
        if line.strip().startswith('>'):
            content = line.strip()[1:].strip()
            elements = parse_markdown_text(content)
            blocks.append({
                "block_type": 15,
                "quote": {
                    "elements": elements,
                    "style": {}
                }
            })
            i += 1
            continue

        # ========== 5. 待办事项 (todo) ==========
        # 格式：- [ ] 或 - [x]
        todo_match = re.match(r'^-\s+\[([ x])\]\s*(.*)', line.strip())
        if todo_match:
            done = todo_match.group(1).lower() == 'x'
            content = todo_match.group(2).strip()
            elements = parse_markdown_text(content)
            blocks.append({
                "block_type": 17,
                "todo": {
                    "elements": elements,
                    "style": {}
                },
                "done": done
            })
            metadata["todo_count"] += 1
            i += 1
            continue

        # ========== 6. 粗体列表项 ==========
        if line.strip().startswith('- **'):
            content = line.strip()[3:]
            content = re.sub(r'\*\*', '', content).strip()
            blocks.append({
                "block_type": 12,
                "bullet": {
                    "elements": [{"text_run": {"content": content, "text_element_style": {"bold": True}}}]
                }
            })
            metadata["list_count"] += 1
            i += 1
            continue

        # ========== 7. 普通无序列表 (bullet) ==========
        if line.strip().startswith('- '):
            content = line.strip()[2:]
            blocks.append({
                "block_type": 12,
                "bullet": {
                    "elements": [{"text_run": {"content": content}}]
                }
            })
            metadata["list_count"] += 1
            i += 1
            continue

        # ========== 8. 有序列表 (ordered) ==========
        if re.match(r'^\d+\.\s', line.strip()):
            content = re.sub(r'^\d+\.\s', '', line.strip())
            blocks.append({
                "block_type": 13,
                "ordered": {
                    "elements": [{"text_run": {"content": content}}]
                }
            })
            metadata["list_count"] += 1
            i += 1
            continue

        # ========== 9. 图片 (image) ==========
        # 格式：![alt](url)
        image_match = re.match(r'^!\[([^\]]*)\]\(([^\)]+)\)$', line.strip())
        if image_match:
            alt = image_match.group(1)
            url = image_match.group(2)
            blocks.append({
                "block_type": 27,
                "image": {
                    "token": url,
                    "width": 0,
                    "height": 0
                }
            })
            metadata["image_count"] += 1
            i += 1
            continue

        # ========== 10. 表格 (table) ==========
        if '|' in line and line.strip():
            table_lines = [line]
            i += 1
            while i < len(lines) and '|' in lines[i]:
                table_lines.append(lines[i])
                i += 1

            # 解析表格
            table_data = []
            for table_line in table_lines:
                if '|---' in table_line or re.match(r'^\|?\s*:?-+:?\s*\|', table_line):
                    continue
                cells = table_line.split('|')
                if cells and cells[0].strip() == '':
                    cells.pop(0)
                if cells and cells[-1].strip() == '':
                    cells.pop()
                processed_cells = []
                for cell in cells:
                    cell = clean_cell_content(cell)
                    if cell:
                        processed_cells.append(cell)
                if processed_cells:
                    table_data.append(processed_cells)

            if table_data and len(table_data) > 1:
                blocks.append({
                    "type": "table",
                    "data": table_data
                })
                metadata["table_count"] += 1
            continue

        # ========== 11. 代码块 (code) ==========
        if line.strip().startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            code_content = '\n'.join(code_lines)
            blocks.append({
                "block_type": 14,
                "code": {
                    "elements": [{"text_run": {"content": code_content}}],
                    "style": {"language": 1}
                }
            })
            metadata["code_count"] += 1
            i += 1
            continue

        # ========== 12. 普通文本 (text) ==========
        if line.strip():
            elements = parse_markdown_text(line)
            blocks.append({
                "block_type": 2,
                "text": {
                    "elements": elements,
                    "style": {}
                }
            })

        i += 1

    metadata["total_blocks"] = len(blocks)

    return {
        "blocks": blocks,
        "metadata": metadata
    }


def main():
    """主函数 - 命令行入口"""
    if len(sys.argv) < 2:
        print("Usage: python md_parser.py <markdown_file> [output_dir]")
        print("Example: python md_parser.py input.md workflow/step1_parse")
        print()
        print("支持的块类型：25 种飞书文档块")
        print("  - 文本块：text, heading1-9")
        print("  - 列表：bullet, ordered, todo")
        print("  - 特殊：code, quote, callout, divider, image")
        print("  - 高级：table, bitable, grid, sheet, board")
        sys.exit(1)

    md_file = Path(sys.argv[1])
    if not md_file.exists():
        print(f"Error: Markdown file not found: {md_file}")
        sys.exit(1)

    # 输出目录
    if len(sys.argv) >= 3:
        output_dir = Path(sys.argv[2])
    else:
        output_dir = Path("output")

    output_dir.mkdir(parents=True, exist_ok=True)

    # 读取 Markdown 文件
    with open(md_file, 'r', encoding='utf-8') as f:
        markdown_content = f.read()

    print("=" * 70)
    print("Markdown Parser - Support 25 Feishu Block Types")
    print("=" * 70)
    print(f"Input file: {md_file}")
    print(f"Content length: {len(markdown_content)} characters")
    print()

    # 解析 Markdown
    start_time = time.time()
    result = parse_markdown_to_blocks(markdown_content, include_first_title=False)
    parse_time = time.time() - start_time

    # 输出 JSON 文件
    blocks_file = output_dir / "blocks.json"
    with open(blocks_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    metadata_file = output_dir / "metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(result["metadata"], f, ensure_ascii=False, indent=2)

    # 打印结果
    print(f"[OK] Parse completed in {parse_time:.2f}s")
    print(f"[OUTPUT] {blocks_file}")
    print(f"[METADATA] {metadata_file}")
    print()
    print("Block Statistics:")
    print(f"  Total blocks: {result['metadata']['total_blocks']}")
    print(f"  Headings: {result['metadata']['heading_count']}")
    print(f"  Tables: {result['metadata']['table_count']}")
    print(f"  Lists: {result['metadata']['list_count']}")
    print(f"  Code blocks: {result['metadata']['code_count']}")
    print(f"  Callouts: {result['metadata']['callout_count']}")
    print(f"  Todos: {result['metadata']['todo_count']}")
    print(f"  Images: {result['metadata']['image_count']}")
    print()
    print(f"[OUTPUT] {blocks_file}")


if __name__ == "__main__":
    main()
