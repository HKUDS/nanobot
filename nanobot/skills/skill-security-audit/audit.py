#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill Security Audit - 第三方技能安全审计工具
检测潜在的代码注入和安全风险
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# 风险等级
CRITICAL = "🔴 CRITICAL"
HIGH = "🟠 HIGH"
MEDIUM = "🟡 MEDIUM"
LOW = "🟢 LOW"

# 危险模式定义
DANGEROUS_PATTERNS = {
    CRITICAL: [
        (r'\beval\s*\(', 'eval() - 可执行任意代码'),
        (r'\bexec\s*\(', 'exec() - 可执行任意代码'),
        (r'\b__import__\s*\(', '__import__() - 动态导入模块'),
        (r'\bcompile\s*\(', 'compile() - 编译代码'),
        (r'os\.system\s*\(', 'os.system() - 执行系统命令'),
        (r'subprocess\.call\s*\([^)]*shell\s*=\s*True', 'subprocess shell=True - 命令注入风险'),
    ],
    HIGH: [
        (r'subprocess\.(run|Popen|call)\s*\(', 'subprocess - 执行外部命令'),
        (r'\.ssh/', 'SSH目录访问'),
        (r'\.aws/', 'AWS凭证目录访问'),
        (r'\.env', '环境变量文件访问'),
        (r'API_KEY|SECRET|PASSWORD|TOKEN', '敏感凭证硬编码'),
        (r'requests\.(get|post)\s*\([^)]*(?!feishu\.cn|open\.feishu)', '非飞书API的网络请求'),
    ],
    MEDIUM: [
        (r'open\s*\([^)]*[\'"]w[\'"]', '文件写入操作'),
        (r'shutil\.(rmtree|move|copy)', 'shutil文件操作'),
        (r'os\.(remove|unlink|rmdir)', '文件删除操作'),
        (r'Path\([\'"]/', '绝对路径访问'),
    ],
    LOW: [
        (r'print\s*\([^)]*password|secret|key', '可能打印敏感信息'),
        (r'logging\.(debug|info)\s*\([^)]*token', '可能记录敏感token'),
    ]
}

# 白名单URL（飞书相关）
ALLOWED_URLS = [
    'open.feishu.cn',
    'feishu.cn',
    'open.larkoffice.com',
    'larkoffice.com',
]


def scan_file(file_path: Path) -> List[Tuple[str, int, str, str]]:
    """扫描单个文件，返回发现的风险"""
    findings = []
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            lines = content.split('\n')
    except Exception as e:
        return [(MEDIUM, 0, str(file_path), f"无法读取文件: {e}")]
    
    for level, patterns in DANGEROUS_PATTERNS.items():
        for pattern, description in patterns:
            for i, line in enumerate(lines, 1):
                # 跳过注释行
                if line.strip().startswith('#'):
                    continue
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append((level, i, str(file_path), f"{description}: {line.strip()[:80]}"))
    
    return findings


def scan_skill(skill_path: str) -> Dict:
    """扫描整个技能目录"""
    skill_dir = Path(skill_path)
    if not skill_dir.exists():
        return {"error": f"目录不存在: {skill_path}"}
    
    results = {
        "skill_path": str(skill_dir),
        "findings": [],
        "summary": {
            CRITICAL: 0,
            HIGH: 0,
            MEDIUM: 0,
            LOW: 0
        }
    }
    
    # 扫描所有Python文件
    for py_file in skill_dir.rglob("*.py"):
        findings = scan_file(py_file)
        results["findings"].extend(findings)
        for level, _, _, _ in findings:
            results["summary"][level] += 1
    
    # 扫描所有Shell脚本
    for sh_file in skill_dir.rglob("*.sh"):
        findings = scan_file(sh_file)
        results["findings"].extend(findings)
        for level, _, _, _ in findings:
            results["summary"][level] += 1
    
    return results


def print_report(results: Dict):
    """打印审计报告"""
    print("\n" + "=" * 60)
    print("🔒 SKILL SECURITY AUDIT REPORT")
    print("=" * 60)
    print(f"\n📁 技能路径: {results['skill_path']}")
    
    print("\n📊 风险摘要:")
    for level, count in results["summary"].items():
        if count > 0:
            print(f"   {level}: {count}")
    
    if not results["findings"]:
        print("\n✅ 未发现安全风险")
        return
    
    print("\n📋 详细发现:")
    for level, line_no, file_path, description in sorted(results["findings"]):
        relative_path = Path(file_path).name
        print(f"\n{level}")
        print(f"   文件: {relative_path}:{line_no}")
        print(f"   问题: {description}")
    
    # 安全建议
    critical_count = results["summary"][CRITICAL]
    high_count = results["summary"][HIGH]
    
    print("\n" + "-" * 60)
    if critical_count > 0:
        print("⛔ 建议: 发现严重风险，不建议安装此技能！")
    elif high_count > 0:
        print("⚠️ 建议: 发现高风险项，请仔细审查代码后再决定是否使用")
    else:
        print("✅ 建议: 风险较低，可以谨慎使用")


def main():
    if len(sys.argv) < 2:
        print("用法: python audit.py <skill_path>")
        print("示例: python audit.py ~/.agents/skills/feishu-doc-orchestrator")
        sys.exit(1)
    
    skill_path = sys.argv[1]
    results = scan_skill(skill_path)
    
    if "error" in results:
        print(f"❌ 错误: {results['error']}")
        sys.exit(1)
    
    print_report(results)


if __name__ == "__main__":
    main()
