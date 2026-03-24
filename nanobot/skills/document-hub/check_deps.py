#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Document Hub 依赖检查和安装脚本
"""

import subprocess
import sys

def check_module(module_name, import_name=None):
    """检查模块是否已安装"""
    if import_name is None:
        import_name = module_name
    
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False

def install_module(module_name):
    """安装模块"""
    print(f"  正在安装 {module_name}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", module_name])
        print(f"  ✅ {module_name} 安装成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ❌ {module_name} 安装失败: {e}")
        return False

def main():
    print("=" * 60)
    print("Document Hub - 依赖检查")
    print("=" * 60)
    
    # 必需的依赖
    required = [
        ("python-docx", "docx"),
        ("pandas", "pandas"),
        ("openpyxl", "openpyxl"),
        ("pdfplumber", "pdfplumber"),
        ("reportlab", "reportlab"),
    ]
    
    # 可选的依赖
    optional = [
        ("pypdf2", "PyPDF2"),
    ]
    
    print("\n📦 检查必需依赖:")
    all_installed = True
    for package, import_name in required:
        if check_module(import_name):
            print(f"  ✅ {package}")
        else:
            print(f"  ❌ {package} - 未安装")
            all_installed = False
    
    print("\n📦 检查可选依赖:")
    for package, import_name in optional:
        if check_module(import_name):
            print(f"  ✅ {package}")
        else:
            print(f"  ⚠️  {package} - 未安装（可选）")
    
    print("\n" + "=" * 60)
    
    if all_installed:
        print("🎉 所有必需依赖已安装！")
        print("\n可以开始使用 Document Hub:")
        print("  from skills.document_hub.document_hub import read, write, convert")
        return 0
    else:
        print("⚠️  部分依赖未安装")
        
        # 询问是否安装
        response = input("\n是否自动安装缺失的依赖？(y/n): ").lower().strip()
        if response == 'y':
            print("\n📥 开始安装...")
            success = True
            for package, import_name in required:
                if not check_module(import_name):
                    if not install_module(package):
                        success = False
            
            if success:
                print("\n✅ 所有依赖安装完成！")
                return 0
            else:
                print("\n❌ 部分依赖安装失败，请手动安装:")
                print("  pip install python-docx pandas openpyxl pdfplumber reportlab")
                return 1
        else:
            print("\n请手动安装依赖:")
            print("  pip install python-docx pandas openpyxl pdfplumber reportlab")
            return 1

if __name__ == "__main__":
    sys.exit(main())
