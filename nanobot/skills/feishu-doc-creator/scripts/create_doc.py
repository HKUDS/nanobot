#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行入口：创建飞书文档"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from feishu_doc_creator import create_doc

if __name__ == "__main__":
    import json
    
    if len(sys.argv) < 4:
        print("用法: python create_doc.py <drive|wiki> <标题> <md文件>")
        sys.exit(1)
    
    doc_type = sys.argv[1]
    title = sys.argv[2]
    md_file = sys.argv[3]
    
    with open(md_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    result = create_doc(title, content, doc_type)
    print(json.dumps(result, ensure_ascii=False, indent=2))
