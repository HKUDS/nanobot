#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信文章抓取工具 - 基于 Playwright
用于抓取微信公众号文章内容
"""

import sys
import argparse
from playwright.sync_api import sync_playwright
from datetime import datetime
import os

def fetch_wechat_article(url, output_path=None):
    """
    抓取微信公众号文章
    
    Args:
        url: 微信文章链接
        output_path: 输出文件路径（可选）
    
    Returns:
        dict: 包含标题、内容、抓取时间等信息
    """
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            
            # 获取标题
            title = page.title()
            
            # 获取正文内容
            content = page.evaluate('''() => {
                const article = document.querySelector('#js_content');
                if (article) {
                    return article.innerText;
                }
                // 备选方案
                return document.body.innerText;
            }''')
            
            browser.close()
            
            result = {
                'title': title,
                'content': content,
                'url': url,
                'fetch_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'success': True
            }
            
            # 如果指定了输出路径，保存到文件
            if output_path:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(f"# {title}\n\n")
                    f.write(f"来源: {url}\n\n")
                    f.write(f"抓取时间: {result['fetch_time']}\n\n")
                    f.write("---\n\n")
                    f.write(content)
                print(f"✅ 已保存到: {output_path}")
            
            return result
            
        except Exception as e:
            browser.close()
            return {
                'success': False,
                'error': str(e),
                'url': url
            }

def main():
    parser = argparse.ArgumentParser(description='抓取微信公众号文章')
    parser.add_argument('url', help='微信文章链接')
    parser.add_argument('-o', '--output', help='输出文件路径')
    
    args = parser.parse_args()
    
    result = fetch_wechat_article(args.url, args.output)
    
    if result['success']:
        print(f"标题: {result['title']}")
        print(f"内容长度: {len(result['content'])} 字符")
        print(f"\n内容预览（前500字）:")
        print(result['content'][:500])
    else:
        print(f"❌ 抓取失败: {result['error']}")
        sys.exit(1)

if __name__ == '__main__':
    main()
