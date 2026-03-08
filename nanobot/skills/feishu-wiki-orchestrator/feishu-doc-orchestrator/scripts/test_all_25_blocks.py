#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书文档完整块类型测试 - 25种已支持块类型
包含所有已支持的块类型，并按照规范执行权限和协作组分配
"""

import sys
import time
from pathlib import Path

# 添加当前技能目录到路径
sys.path.insert(0, '.claude/skills/feishu-doc-creator-with-permission/scripts')
sys.path.insert(0, '.claude/skills/feishu-block-adder/scripts')

from doc_creator_with_permission import load_config, get_access_token, create_document, add_permission_member, transfer_owner
from block_adder import add_children_to_block

# ==================== 25种已支持的块类型定义 ====================

def get_all_supported_blocks():
    """返回所有25种已支持的块类型定义"""
    return [
        # 基础文本块 (11种)
        {"block_type": 2, "text": {"elements": [{"text_run": {"content": "普通文本块"}}], "style": {}}, "name": "Text", "desc": "普通文本"},
        {"block_type": 3, "heading1": {"elements": [{"text_run": {"content": "一级标题"}}], "style": {}}, "name": "Heading1", "desc": "一级标题"},
        {"block_type": 4, "heading2": {"elements": [{"text_run": {"content": "二级标题"}}], "style": {}}, "name": "Heading2", "desc": "二级标题"},
        {"block_type": 5, "heading3": {"elements": [{"text_run": {"content": "三级标题"}}], "style": {}}, "name": "Heading3", "desc": "三级标题"},
        {"block_type": 6, "heading4": {"elements": [{"text_run": {"content": "四级标题"}}], "style": {}}, "name": "Heading4", "desc": "四级标题"},
        {"block_type": 7, "heading5": {"elements": [{"text_run": {"content": "五级标题"}}], "style": {}}, "name": "Heading5", "desc": "五级标题"},
        {"block_type": 8, "heading6": {"elements": [{"text_run": {"content": "六级标题"}}], "style": {}}, "name": "Heading6", "desc": "六级标题"},
        {"block_type": 9, "heading7": {"elements": [{"text_run": {"content": "七级标题"}}], "style": {}}, "name": "Heading7", "desc": "七级标题"},
        {"block_type": 10, "heading8": {"elements": [{"text_run": {"content": "八级标题"}}], "style": {}}, "name": "Heading8", "desc": "八级标题"},
        {"block_type": 11, "heading9": {"elements": [{"text_run": {"content": "九级标题"}}], "style": {}}, "name": "Heading9", "desc": "九级标题"},
        {"block_type": 34, "quote_container": {}, "name": "QuoteContainer", "desc": "引用容器"},

        # 列表块 (4种)
        {"block_type": 12, "bullet": {"elements": [{"text_run": {"content": "无序列表项"}}]}, "name": "Bullet", "desc": "无序列表"},
        {"block_type": 13, "ordered": {"elements": [{"text_run": {"content": "有序列表项"}}]}, "name": "Ordered", "desc": "有序列表"},
        {"block_type": 17, "todo": {"elements": [{"text_run": {"content": "待办事项"}}], "style": {}}, "done": False, "name": "Todo", "desc": "待办事项(未完成)"},
        {"block_type": 17, "todo": {"elements": [{"text_run": {"content": "已完成事项"}}], "style": {}}, "done": True, "name": "Todo-Done", "desc": "待办事项(已完成)"},

        # 特殊块 (5种)
        {"block_type": 14, "code": {"elements": [{"text_run": {"content": "print('Hello, Feishu!')"}}], "style": {"language": 49}}, "name": "Code", "desc": "代码块(Python)"},
        {"block_type": 15, "quote": {"elements": [{"text_run": {"content": "这是一段引用文本"}}]}, "name": "Quote", "desc": "引用块"},
        {"block_type": 19, "callout": {"elements": [{"text_run": {"content": "这是一个信息提示框"}}], "emoji_id": "information_source", "background_color": 5, "border_color": 5}, "name": "Callout", "desc": "高亮块(info)"},
        {"block_type": 22, "divider": {}, "name": "Divider", "desc": "分割线"},
        {"block_type": 35, "task": {}, "name": "Task", "desc": "任务块(空)"},

        # AI块 (1种)
        {"block_type": 52, "ai_template": {}, "name": "AITemplate", "desc": "AI模板块(只读)"},

        # 高级块 (5种)
        {"block_type": 18, "bitable": {"view_type": 1}, "name": "Bitable", "desc": "多维表格(数据表视图)"},
        {"block_type": 24, "grid": {"column_size": 2}, "name": "Grid", "desc": "分栏(2列)"},
        {"block_type": 30, "sheet": {"row_size": 5, "column_size": 3}, "name": "Sheet", "desc": "电子表格(5行3列)"},
        {"block_type": 31, "table": {"property": {"row_size": 3, "column_size": 3}}, "name": "Table", "desc": "表格(3行3列)"},
        {"block_type": 43, "board": {}, "name": "Board", "desc": "画板"},
    ]


def main():
    """主函数"""

    print("=" * 70)
    print("飞书文档完整块类型测试 - 25种已支持块类型")
    print("=" * 70)

    config = load_config()
    if not config:
        print("错误: 无法加载配置文件")
        return

    # 步骤1: 获取 tenant_access_token
    print("\n[步骤 1] 获取 tenant_access_token...")
    token = get_access_token(config, use_user_token=False)
    print("  Token 获取成功")

    # 步骤2: 创建文档
    print("\n[步骤 2] 创建测试文档...")
    doc_title = "飞书完整块类型测试-25种-" + str(int(time.time()))[-6:]
    doc_id = create_document(token, config, doc_title)
    print(f"  文档创建成功!")
    print(f"  文档 ID: {doc_id}")

    # 步骤3: 创建所有支持的块
    print("\n[步骤 3] 创建25种已支持的块类型...")
    blocks = get_all_supported_blocks()

    # 添加标题
    header_blocks = [
        {"block_type": 3, "heading1": {"elements": [{"text_run": {"content": "飞书文档块类型完整测试 - 25种已支持块类型"}}], "style": {}}},
        {"block_type": 2, "text": {"elements": [{"text_run": {"content": f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"}}], "style": {}}},
        {"block_type": 22, "divider": {}},
        {"block_type": 4, "heading2": {"elements": [{"text_run": {"content": "25种已支持的块类型清单"}}], "style": {}}},
    ]
    add_children_to_block(token, config, doc_id, doc_id, header_blocks)

    # 分批添加块，每批 25 个
    batch_size = 25
    total_batches = (len(blocks) + batch_size - 1) // batch_size

    for i in range(0, len(blocks), batch_size):
        batch = blocks[i:i+batch_size]
        batch_num = i // batch_size + 1
        print(f"  添加第 {batch_num}/{total_batches} 批 ({len(batch)} 个块)...")
        try:
            add_children_to_block(token, config, doc_id, doc_id, batch)
            print(f"    第 {batch_num} 批添加成功!")
        except Exception as e:
            print(f"    第 {batch_num} 批添加失败: {e}")

    print(f"  总共创建了 {len(blocks)} 个块")

    # 步骤4: 添加协作者权限
    print("\n[步骤 4] 添加协作者权限...")
    collaborator_id = config.get('FEISHU_AUTO_COLLABORATOR_ID', '')
    if not collaborator_id:
        print("  警告: 配置文件中没有 FEISHU_AUTO_COLLABORATOR_ID")
    else:
        try:
            result = add_permission_member(token, config, doc_id, collaborator_id, "openid", "full_access")
            if result.get("code") == 0:
                print("  协作者添加成功!")
            else:
                print(f"  协作者添加失败: {result}")
        except Exception as e:
            print(f"  协作者添加失败: {e}")

    # 步骤5: 转移所有权
    print("\n[步骤 5] 转移文档所有权...")
    if not collaborator_id:
        print("  跳过所有权转移步骤")
    else:
        try:
            result = transfer_owner(doc_id, collaborator_id)
            print("  所有权转移成功!")
        except Exception as e:
            print(f"  所有权转移失败: {e}")

    # 完成
    print("\n" + "=" * 70)
    print("测试完成!")
    print("=" * 70)
    print(f"  文档标题: {doc_title}")
    print(f"  文档 ID: {doc_id}")
    print(f"  块数量: {len(blocks)}")
    print(f"  文档链接: https://my.feishu.cn/docx/{doc_id}")
    print()

    # 统计信息
    print("块类型统计:")
    print("-" * 50)
    print("  基础文本块: 11 种 (Text, Heading1-9, QuoteContainer)")
    print("  列表块: 4 种 (Bullet, Ordered, Todo x2)")
    print("  特殊块: 5 种 (Code, Quote, Callout, Divider, Task)")
    print("  AI块: 1 种 (AITemplate)")
    print("  高级块: 5 种 (Bitable, Grid, Sheet, Table, Board)")
    print(f"  总计: {len(blocks)} 个块实例，涵盖 25 种不同类型")
    print()


if __name__ == "__main__":
    main()
