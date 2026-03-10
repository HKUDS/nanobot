#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档验证器 - 子技能5
使用 Playwright 验证文档是否创建成功
输出：verify_result.json
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime


def clean_zero_width_chars(text):
    """清理零宽字符，避免乱码

    零宽字符包括：
    - \u200b: 零宽空格 (Zero Width Space)
    - \u200c: 零宽非连字符 (Zero Width Non-Joiner)
    - \u200d: 零宽连字符 (Zero Width Joiner)
    - \u202a-\u202e: 双向控制字符
    - \u2060-\u2064: 其他零宽字符
    - \ufeff: 零宽非断空格 (Zero Width No-Break Space)
    - \u00ad: 软连字符 (Soft Hyphen)
    """
    if not text:
        return ""
    # 移除所有零宽字符和双向控制字符
    # 使用字符范围 [\u200b-\u200d] 匹配零宽字符
    # 使用范围 [\u202a-\u202e] 匹配双向控制字符
    # 使用范围 [\u2060-\u2064] 匹配其他零宽字符
    text = re.sub(r'[\u200b-\u200d\u202a-\u202e\u2060-\u2064\ufeff\u00ad]', '', text)
    return text.strip()


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("Usage: python doc_verifier.py <doc_info.json> [output_dir]")
        sys.exit(1)

    doc_info_file = Path(sys.argv[1])

    if len(sys.argv) >= 3:
        output_dir = Path(sys.argv[2])
    else:
        output_dir = Path("output")

    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载文档信息
    print(f"[feishu-doc-verifier] Loading doc info from: {doc_info_file}")
    with open(doc_info_file, 'r', encoding='utf-8') as f:
        doc_info = json.load(f)

    doc_id = doc_info["document_id"]
    doc_url = doc_info["document_url"]
    title = doc_info.get("title", "未命名文档")

    print(f"[feishu-doc-verifier] Document ID: {doc_id}")
    print(f"[feishu-doc-verifier] Document URL: {doc_url}")

    # 结果
    result = {
        "success": False,
        "document_id": doc_id,
        "document_url": doc_url,
        "page_loaded": False,
        "page_title": "",
        "screenshot": "",
        "errors": []
    }

    # 使用 Playwright 验证
    print("\n[feishu-doc-verifier] Starting Playwright verification...")
    try:
        from playwright.sync_api import sync_playwright

        # 使用持久化上下文
        user_data_dir = Path(__file__).parent.parent.parent.parent / "skills" / "feishu-doc-creator" / "playwright_data"

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=True
            )
            page = context.new_page()

            # 访问文档
            page.goto(doc_url)
            page.wait_for_timeout(5000)

            # 获取页面信息
            page_title = page.title()
            # 清理零宽字符，避免乱码
            page_title = clean_zero_width_chars(page_title)
            result["page_loaded"] = True
            result["page_title"] = page_title

            # 简单验证：检查页面是否正常加载
            if page_title and len(page_title) > 0:
                result["success"] = True
                print(f"[OK] 文档验证成功 - 页面正常加载")
                print(f"[OK] 页面标题: {page_title}")
            else:
                print(f"[WARN] 文档验证失败 - 页面可能无法正常访问")

            # 截图（可选）
            screenshot_file = output_dir / "screenshot.png"
            page.screenshot(path=str(screenshot_file))
            result["screenshot"] = str(screenshot_file)

            context.close()

    except Exception as e:
        error_msg = str(e)
        result["errors"].append(f"验证异常: {error_msg}")
        print(f"[WARN] 文档验证异常: {error_msg}")
        result["page_loaded"] = False

    result["verified_at"] = datetime.now().isoformat()

    # 保存结果
    result_file = output_dir / "verify_result.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[feishu-doc-verifier] Output: {result_file}")
    print(f"\n[OUTPUT] {result_file}")


if __name__ == "__main__":
    main()
