#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行入口：转换文档格式"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from feishu_doc_converter import convert

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python convert.py <doc|url> <source> [output.md]")
        print("  doc: 飞书文档ID或URL")
        print("  url: 外部文章链接")
        sys.exit(1)
    
    source_type = sys.argv[1]
    source = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) >= 4 else None
    
    try:
        md_content = convert(source, source_type)
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(md_content)
            print(f"已保存到: {output_file}")
        else:
            print(md_content)
    except Exception as e:
        print(f"转换失败: {e}")
        sys.exit(1)
