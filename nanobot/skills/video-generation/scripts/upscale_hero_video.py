#!/usr/bin/env python3
"""
视频超分到 4K
Usage: python upscale_hero_video.py <video_path> [--resolution 4k] [--output output_4k.mp4]
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from video_core import upscale_video


def main():
    parser = argparse.ArgumentParser(description='视频超分到高分辨率')
    parser.add_argument('video', help='输入视频路径')
    parser.add_argument('--resolution', '-r', default='4k',
                       choices=['720p', '1080p', '2k', '4k'],
                       help='目标分辨率')
    parser.add_argument('--output', '-o', help='输出视频路径（默认: 原文件名_4k.mp4）')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.video):
        print(f"❌ 视频不存在: {args.video}")
        return 1
    
    # 自动生成输出文件名
    if not args.output:
        base, ext = os.path.splitext(args.video)
        args.output = f"{base}_{args.resolution}{ext}"
    
    print("="*60)
    print("🔍 视频超分")
    print("="*60)
    print(f"输入: {args.video}")
    print(f"目标分辨率: {args.resolution}")
    print(f"输出: {args.output}")
    print("-"*60)
    
    try:
        output = upscale_video(args.video, args.output, args.resolution)
        print("="*60)
        print(f"✅ 超分成功: {output}")
        return 0
    except Exception as e:
        print(f"❌ 超分失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
