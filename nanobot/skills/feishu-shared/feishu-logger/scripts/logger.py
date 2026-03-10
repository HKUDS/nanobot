#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志记录器 - 子技能6
汇总所有步骤结果，记录到日志文件
输出：CREATED_DOCS.md, created_docs.json
"""

import sys
import json
from pathlib import Path
from datetime import datetime


def load_json(file_path):
    """加载 JSON 文件"""
    if file_path.exists():
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("Usage: python logger.py <workflow_dir> [output_dir]")
        sys.exit(1)

    workflow_dir = Path(sys.argv[1])

    if len(sys.argv) >= 3:
        output_dir = Path(sys.argv[2])
    else:
        # 默认输出到父目录（通常是主技能目录）
        output_dir = Path(__file__).parent.parent  # feishu-doc-orchestrator

    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载所有结果文件
    print(f"[feishu-logger] Loading results from: {workflow_dir}")

    blocks_data = load_json(workflow_dir / "step1_parse" / "blocks.json")
    doc_info = load_json(workflow_dir / "step2_create_with_permission" / "doc_with_permission.json")
    add_result = load_json(workflow_dir / "step3_add_blocks" / "add_result.json")
    verify_result = load_json(workflow_dir / "step4_verify" / "verify_result.json")

    # 汇总信息
    doc_id = doc_info.get("document_id", "")
    doc_url = doc_info.get("document_url", "")
    title = doc_info.get("title", "未命名文档")
    created_at = doc_info.get("created_at", "")

    # 从 doc_with_permission.json 获取权限信息
    permission = doc_info.get("permission", {})

    # 解析元数据
    metadata = blocks_data.get("metadata", {})

    # 汇总日志条目
    log_entry = {
        "title": title,
        "time": created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "document_id": doc_id,
        "url": doc_url,
        "source_file": "",  # 可以从输入参数传入
        "collaborator_added": permission.get("collaborator_added", False),
        "owner_transferred": permission.get("owner_transferred", False),
        "user_has_full_control": permission.get("user_has_full_control", False),
        "document_verified": verify_result.get("success", False),
        "tables_created": add_result.get("tables_created", 0),
        "blocks_created": add_result.get("total_blocks", 0)
    }

    # 更新 JSON 日志
    json_log_file = output_dir / "created_docs.json"
    json_logs = []

    if json_log_file.exists():
        with open(json_log_file, 'r', encoding='utf-8') as f:
            json_logs = json.load(f)

    json_logs.append(log_entry)

    with open(json_log_file, 'w', encoding='utf-8') as f:
        json.dump(json_logs, f, ensure_ascii=False, indent=2)

    # 更新 Markdown 日志
    md_log_file = output_dir / "CREATED_DOCS.md"

    md_entry = f"""
### {title}

- **时间**: {log_entry['time']}
- **文档ID**: `{doc_id}`
- **URL**: [{doc_url}]({doc_url})
- **collaborator_added**: {log_entry['collaborator_added']}
- **owner_transferred**: {log_entry['owner_transferred']}
- **user_has_full_control**: {log_entry['user_has_full_control']}
- **document_verified**: {log_entry['document_verified']}
- **tables_created**: {log_entry['tables_created']}
- **blocks_created**: {log_entry['blocks_created']}
"""

    if md_log_file.exists():
        with open(md_log_file, 'r', encoding='utf-8') as f:
            md_content = f.read()
        # 在文档列表后面追加
        if "## 文档列表" in md_content:
            md_content = md_content.replace("## 文档列表", f"## 文档列表{md_entry}")
        else:
            md_content = f"# 飞书文档创建日志\n\n## 文档列表{md_entry}"
    else:
        md_content = f"# 飞书文档创建日志\n\n## 文档列表{md_entry}"

    with open(md_log_file, 'w', encoding='utf-8') as f:
        f.write(md_content)

    # 打印摘要
    print(f"\n[feishu-logger] Log entry created")
    print(f"[feishu-logger] Title: {title}")
    print(f"[feishu-logger] URL: {doc_url}")
    print(f"[feishu-logger] Permissions: collaborator={log_entry['collaborator_added']}, owner={log_entry['owner_transferred']}")
    print(f"[feishu-logger] Verified: {log_entry['document_verified']}")
    print(f"[feishu-logger] Tables: {log_entry['tables_created']}, Blocks: {log_entry['blocks_created']}")
    print(f"\n[feishu-logger] JSON log: {json_log_file}")
    print(f"[feishu-logger] Markdown log: {md_log_file}")


if __name__ == "__main__":
    main()
