#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Content Extractor 示例脚本
演示如何使用内容提取功能
"""

import sys
sys.path.insert(0, '/Users/delta/.nanobot/workspace')

from skills.content_extractor.content_extractor import (
    extract, batch_extract, detect_platform, Platform
)

def demo_detect_platform():
    """演示平台检测"""
    print("=" * 60)
    print("演示：平台检测")
    print("=" * 60)
    
    test_urls = [
        ("https://www.xiaoyuzhoufm.com/episode/xxx", "小宇宙播客"),
        ("https://v.douyin.com/xxx", "抖音"),
        ("https://mp.weixin.qq.com/s/xxx", "微信公众号"),
        ("https://www.bilibili.com/video/BVxxx", "B站"),
        ("https://www.xiaohongshu.com/xxx", "小红书"),
        ("https://unknown-site.com/xxx", "未知平台"),
    ]
    
    for url, name in test_urls:
        platform = detect_platform(url)
        status = "✅" if platform != Platform.UNKNOWN else "❌"
        print(f"  {status} {name}: {platform.value}")
    
    print("\n✅ 平台检测演示完成")

def demo_extract_structure():
    """演示提取结果结构"""
    print("\n" + "=" * 60)
    print("演示：提取结果结构")
    print("=" * 60)
    
    # 模拟提取结果
    from skills.content_extractor.content_extractor import ExtractResult
    
    result = ExtractResult(
        platform=Platform.XIAOYUZHOU,
        title="示例播客标题",
        content="这是播客的描述内容...",
        author="主播名称",
        media_urls=["https://example.com/audio.mp3"],
        metadata={"url": "https://example.com/episode/xxx"}
    )
    
    print(f"\n提取结果:")
    print(f"  平台: {result.platform.value}")
    print(f"  标题: {result.title}")
    print(f"  作者: {result.author}")
    print(f"  内容: {result.content[:30]}...")
    print(f"  媒体URL: {len(result.media_urls)} 个")
    print(f"  图片: {len(result.images)} 个")
    
    print("\n✅ 结果结构演示完成")

def demo_workflow_integration():
    """演示工作流集成"""
    print("\n" + "=" * 60)
    print("演示：工作流集成（伪代码）")
    print("=" * 60)
    
    print("""
工作流1: 播客 → 笔记
```python
from skills.content_extractor.content_extractor import extract
from skills.document_hub.document_hub import write

# 1. 提取播客内容
result = extract("https://www.xiaoyuzhoufm.com/episode/xxx")

# 2. 生成Word笔记
content = {
    "title": result.title,
    "paragraphs": [
        f"来源：小宇宙播客",
        f"作者：{result.author}",
        "",
        "内容：",
        result.content
    ]
}
write("播客笔记.docx", content)
```

工作流2: 视频 → 音频提取
```python
from skills.content_extractor.content_extractor import extract
from skills.document_hub.document_hub import get_hub

hub = get_hub()

# 1. 提取并下载视频
result = extract(url, download_media=True, save_path="./downloads")

# 2. 提取音频
video_path = result.metadata['downloaded_video']
hub.convert_media(video_path, "audio.mp3")
```
""")
    
    print("✅ 工作流集成演示完成")

def main():
    """运行所有演示"""
    print("\n" + "🎧" * 30)
    print("Content Extractor - 内容提取中心")
    print("🎧" * 30)
    
    demo_detect_platform()
    demo_extract_structure()
    demo_workflow_integration()
    
    print("\n" + "=" * 60)
    print("🎉 所有演示完成！")
    print("=" * 60)
    print("\n提示：")
    print("  • 实际提取需要安装: pip install playwright requests")
    print("  • 初始化浏览器: playwright install chromium")
    print("  • 微信公众号提取需要: wechat-article-fetcher skill")

if __name__ == "__main__":
    main()
