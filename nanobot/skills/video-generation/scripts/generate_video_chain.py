#!/usr/bin/env python3
"""
生成视频链（多段视频拼接）
Usage: python generate_video_chain.py <initial_image> [--segments 4] [--prompt "..."] [--output final_chain.mp4]
"""

import argparse
import sys
import os
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from video_core import generate_video_from_image, upload_file, submit_i2v_task, poll_result, download_file


def extract_last_frame(video_path: str, output_path: str):
    """提取视频最后一帧"""
    cmd = [
        "ffmpeg", "-y", "-sseof", "-0.1",
        "-i", video_path,
        "-vframes", "1", "-q:v", "2",
        output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def concat_videos(video_list: list, output_path: str):
    """拼接多个视频"""
    # 创建文件列表
    list_file = "/tmp/concat_list.txt"
    with open(list_file, "w") as f:
        for v in video_list:
            f.write(f"file '{os.path.abspath(v)}'\\n")
    
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy",
        output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description='生成视频链')
    parser.add_argument('image', help='初始图片路径')
    parser.add_argument('--segments', '-n', type=int, default=4,
                       help='视频段数')
    parser.add_argument('--prompt', '-p',
                       default='Gentle flowing motion with glowing particles, subtle neon light effects, futuristic cyberpunk feeling',
                       help='视频描述 prompt')
    parser.add_argument('--duration', '-d', type=int, default=5,
                       help='每段时长（秒）')
    parser.add_argument('--output', '-o', default='video_chain.mp4',
                       help='最终输出路径')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.image):
        print(f"❌ 图片不存在: {args.image}")
        return 1
    
    print("="*60)
    print("🎬 视频链生成")
    print("="*60)
    print(f"初始图片: {args.image}")
    print(f"段数: {args.segments}")
    print(f"每段时长: {args.duration}秒")
    print(f"Prompt: {args.prompt}")
    print(f"最终输出: {args.output}")
    print("-"*60)
    
    videos = []
    current_image = args.image
    
    try:
        for i in range(args.segments):
            print(f"\\n📽️  生成第 {i+1}/{args.segments} 段...")
            
            # 生成视频
            video_path = f"/tmp/chain_seg_{i+1}.mp4"
            generate_video_from_image(current_image, args.prompt, video_path, args.duration)
            videos.append(video_path)
            
            # 如果不是最后一段，提取最后一帧
            if i < args.segments - 1:
                current_image = f"/tmp/chain_last_{i+1}.jpg"
                print(f"   提取最后一帧...")
                extract_last_frame(video_path, current_image)
        
        # 拼接所有视频
        print(f"\\n🔗 拼接 {len(videos)} 段视频...")
        concat_videos(videos, args.output)
        
        # 清理临时文件
        for v in videos:
            os.remove(v)
        
        print("="*60)
        print(f"✅ 视频链生成成功: {args.output}")
        print(f"   总时长: ~{args.segments * args.duration}秒")
        return 0
        
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
