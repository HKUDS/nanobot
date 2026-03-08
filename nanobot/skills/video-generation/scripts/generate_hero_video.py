#!/usr/bin/env python3
"""
从图片生成 Hero 背景视频
Usage: python generate_hero_video.py <image_path> [--prompt "..."] [--duration 5] [--output output.mp4]
"""

import argparse
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from video_core import generate_video_from_image


def main():
    parser = argparse.ArgumentParser(description='从图片生成 Hero 背景视频')
    parser.add_argument('image', help='输入图片路径')
    parser.add_argument('--prompt', '-p', 
                       default='Gentle flowing motion with glowing particles, subtle neon light effects, futuristic cyberpunk feeling, smooth ambient movement',
                       help='视频描述 prompt')
    parser.add_argument('--duration', '-d', type=int, default=5,
                       help='视频时长（秒），可选 5 或 8')
    parser.add_argument('--output', '-o', default='hero_video.mp4',
                       help='输出视频路径')
    parser.add_argument('--model', '-m', default='wavespeed-ai/wan-2.2/i2v-480p',
                       help='模型路径')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.image):
        print(f"❌ 图片不存在: {args.image}")
        return 1
    
    print("="*60)
    print("🎬 Hero 视频生成")
    print("="*60)
    print(f"输入: {args.image}")
    print(f"Prompt: {args.prompt}")
    print(f"时长: {args.duration}秒")
    print(f"模型: {args.model}")
    print(f"输出: {args.output}")
    print("-"*60)
    
    try:
        output = generate_video_from_image(
            args.image, 
            args.prompt, 
            args.output,
            args.duration,
            args.model
        )
        print("="*60)
        print(f"✅ 生成成功: {output}")
        return 0
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
