#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document Hub 示例脚本
演示如何使用统一文档处理功能
"""

import os
import sys

# 添加workspace到路径
sys.path.insert(0, '~/.hiperone/workspace')

from skills.document_hub.document_hub import (
    read, write, convert, get_info,
    DocumentHub, DocumentReadError, DocumentWriteError
)

def demo_read_word():
    """演示读取Word文档"""
    print("=" * 50)
    print("演示：读取Word文档")
    print("=" * 50)
    
    # 创建一个测试Word文档
    test_content = {
        "title": "测试文档",
        "paragraphs": [
            "这是第一段文字。",
            {"text": "这是加粗的第二段。", "bold": True},
            "这是第三段。"
        ],
        "tables": [
            [["项目", "金额", "备注"],
             ["服务费", "800000", "年度合作"],
             ["附加服务", "50000", "可选"]]
        ]
    }
    
    write("test_document.docx", test_content)
    print("✅ 测试文档已创建: test_document.docx")
    
    # 读取文档
    doc = read("test_document.docx")
    print(f"\n📄 文档内容:")
    print(f"  - 段落数: {len(doc['paragraphs'])}")
    print(f"  - 表格数: {len(doc['tables'])}")
    
    print("\n段落内容:")
    for i, para in enumerate(doc['paragraphs'][:3], 1):
        text = para if isinstance(para, str) else para.get("text", "")
        print(f"  {i}. {text}")
    
    if doc['tables']:
        print("\n表格内容:")
        for row in doc['tables'][0]:
            print(f"  {row}")
    
    # 清理
    os.remove("test_document.docx")
    print("\n✅ 演示完成，测试文件已清理")

def demo_read_excel():
    """演示读取Excel文档"""
    print("\n" + "=" * 50)
    print("演示：读取Excel文档")
    print("=" * 50)
    
    # 创建测试Excel
    excel_content = {
        "sheets": {
            "收入": {
                "data": [
                    {"月份": "1月", "收入": 100000, "成本": 60000},
                    {"月份": "2月", "收入": 120000, "成本": 70000},
                    {"月份": "3月", "收入": 150000, "成本": 80000}
                ]
            },
            "支出": {
                "data": [
                    {"项目": "人力", "金额": 50000},
                    {"项目": "运营", "金额": 30000}
                ]
            }
        }
    }
    
    write("test_excel.xlsx", excel_content)
    print("✅ 测试Excel已创建: test_excel.xlsx")
    
    # 读取Excel
    excel = read("test_excel.xlsx")
    print(f"\n📊 Excel内容:")
    print(f"  - Sheet数量: {excel['metadata']['sheet_count']}")
    print(f"  - Sheet名称: {', '.join(excel['metadata']['sheet_names'])}")
    
    for sheet_name, sheet_data in excel['sheets'].items():
        print(f"\n  Sheet: {sheet_name}")
        print(f"    - 行数: {sheet_data['row_count']}")
        print(f"    - 列数: {sheet_data['column_count']}")
        print(f"    - 数据预览:")
        for row in sheet_data['data'][:2]:
            print(f"      {row}")
    
    # 清理
    os.remove("test_excel.xlsx")
    print("\n✅ 演示完成，测试文件已清理")

def demo_convert():
    """演示格式转换"""
    print("\n" + "=" * 50)
    print("演示：Markdown转Word")
    print("=" * 50)
    
    # 创建测试Markdown
    md_content = """# 年度合作计划

## 一、合作背景

双方本着互利共赢的原则，达成以下合作。

## 二、合作内容

- 项目A：技术服务
- 项目B：咨询服务
- 项目C：培训服务

## 三、费用明细

| 项目 | 金额 | 说明 |
|------|------|------|
| 基础服务 | 800000 | 年度费用 |
| 附加服务 | 50000 | 可选 |

## 四、其他条款

详见正式合同。
"""
    
    with open("test_input.md", "w", encoding="utf-8") as f:
        f.write(md_content)
    print("✅ 测试Markdown已创建: test_input.md")
    
    # 转换为Word
    try:
        convert("test_input.md", "test_output.docx")
        print("✅ 转换成功: test_input.md -> test_output.docx")
        
        # 验证转换结果
        doc = read("test_output.docx")
        print(f"\n📄 转换后文档:")
        print(f"  - 段落数: {len(doc['paragraphs'])}")
        print(f"  - 表格数: {len(doc['tables'])}")
        
    except Exception as e:
        print(f"⚠️  转换需要LibreOffice支持: {e}")
    
    # 清理
    for f in ["test_input.md", "test_output.docx"]:
        if os.path.exists(f):
            os.remove(f)
    print("\n✅ 演示完成，测试文件已清理")

def demo_error_handling():
    """演示错误处理"""
    print("\n" + "=" * 50)
    print("演示：错误处理")
    print("=" * 50)
    
    # 尝试读取不存在的文件
    print("\n1. 读取不存在的文件:")
    try:
        read("not_exist.docx")
    except DocumentReadError as e:
        print(f"   ✅ 捕获错误: {e}")
    
    # 尝试读取不支持的格式
    print("\n2. 读取不支持的格式:")
    try:
        read("test.xyz")
    except DocumentReadError as e:
        print(f"   ✅ 捕获错误: {e}")
    
    print("\n✅ 错误处理演示完成")

def demo_info():
    """演示获取文档信息"""
    print("\n" + "=" * 50)
    print("演示：获取文档信息")
    print("=" * 50)
    
    # 创建一个测试文档
    content = {
        "title": "测试文档",
        "paragraphs": ["段落1", "段落2", "段落3"],
        "tables": [[["A", "B"], ["C", "D"]]]
    }
    write("test_info.docx", content)
    
    # 获取信息
    info = get_info("test_info.docx")
    print(f"\n📋 文档信息:")
    print(f"  - 类型: {info.doc_type.value}")
    print(f"  - 大小: {info.size} bytes")
    print(f"  - 段落数: {info.paragraphs}")
    print(f"  - 表格数: {info.tables}")
    
    # 清理
    os.remove("test_info.docx")
    print("\n✅ 演示完成")

def main():
    """运行所有演示"""
    print("\n" + "🦞" * 25)
    print("Document Hub - 统一文档处理中心")
    print("🦞" * 25)
    
    try:
        demo_read_word()
        demo_read_excel()
        demo_convert()
        demo_error_handling()
        demo_info()
        
        print("\n" + "=" * 50)
        print("🎉 所有演示完成！")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ 演示出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
