#!/usr/bin/env python3
"""
视频生成核心模块 - WaveSpeed AI 接口
"""

import requests
import time
import os
from typing import Optional

API_KEY = os.getenv("WAVESPEED_KEY")
BASE_URL = "https://api.wavespeed.ai/api/v3"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}


def upload_file(file_path: str) -> str:
    """上传文件到 WaveSpeed"""
    with open(file_path, 'rb') as f:
        r = requests.post(
            f"{BASE_URL}/media/upload/binary",
            headers=HEADERS,
            files={"file": f}
        )
    result = r.json()
    if result.get("code") == 200:
        return result["data"]["download_url"]
    raise Exception(f"上传失败: {result.get('message')}")


def submit_i2v_task(image_url: str, prompt: str, duration: int = 5, 
                   model: str = "wavespeed-ai/wan-2.2/i2v-480p") -> dict:
    """提交图生视频任务"""
    payload = {
        "image": image_url,
        "prompt": prompt,
        "duration": duration,
        "enable_prompt_expansion": False
    }
    r = requests.post(f"{BASE_URL}/{model}", headers=JSON_HEADERS, json=payload)
    result = r.json()
    if result.get("code") == 200:
        return result["data"]
    raise Exception(f"提交任务失败: {result.get('message')}")


def submit_upscale_task(video_url: str, target_resolution: str = "4k") -> dict:
    """提交视频超分任务"""
    payload = {
        "video": video_url,
        "target_resolution": target_resolution
    }
    r = requests.post(
        f"{BASE_URL}/wavespeed-ai/video-upscaler-pro",
        headers=JSON_HEADERS,
        json=payload
    )
    result = r.json()
    if result.get("code") == 200:
        return result["data"]
    raise Exception(f"提交超分任务失败: {result.get('message')}")


def poll_result(task_id: str, get_url: Optional[str] = None, 
                max_attempts: int = 60, interval: int = 5) -> str:
    """轮询任务结果"""
    poll_url = get_url or f"{BASE_URL}/predictions/{task_id}"
    
    for attempt in range(max_attempts):
        r = requests.get(poll_url, headers=HEADERS)
        result = r.json()
        
        if result.get("code") == 200:
            data = result["data"]
            status = data.get("status")
            
            if status == "completed":
                outputs = data.get("outputs", [])
                if outputs:
                    return outputs[0]
                raise Exception("任务完成但无输出")
            elif status == "failed":
                raise Exception(f"任务失败: {data.get('error', '未知错误')}")
            
            print(f"  等待中... ({attempt+1}/{max_attempts}) - {status}")
        
        time.sleep(interval)
    
    raise Exception("轮询超时")


def download_file(url: str, output_path: str):
    """下载文件"""
    r = requests.get(url, stream=True)
    with open(output_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"✅ 已下载: {output_path}")


def generate_video_from_image(image_path: str, prompt: str, 
                              output_path: str, duration: int = 5,
                              model: str = "wavespeed-ai/wan-2.2/i2v-480p") -> str:
    """
    一键生成视频
    
    Args:
        image_path: 输入图片路径
        prompt: 视频描述 prompt
        output_path: 输出视频路径
        duration: 视频时长（5或8秒）
        model: 模型路径
    
    Returns:
        输出视频路径
    """
    print(f"🎬 生成视频: {image_path}")
    print(f"   Prompt: {prompt[:50]}...")
    
    # 1. 上传图片
    print("📤 上传图片...")
    image_url = upload_file(image_path)
    
    # 2. 提交任务
    print("📝 提交生成任务...")
    task = submit_i2v_task(image_url, prompt, duration, model)
    
    # 3. 轮询结果
    print("⏳ 等待生成...")
    video_url = poll_result(task["id"], task["urls"]["get"])
    
    # 4. 下载视频
    download_file(video_url, output_path)
    
    return output_path


def upscale_video(video_path: str, output_path: str, target_resolution: str = "4k") -> str:
    """
    一键视频超分
    
    Args:
        video_path: 输入视频路径
        output_path: 输出视频路径
        target_resolution: 目标分辨率 (720p, 1080p, 2k, 4k)
    
    Returns:
        输出视频路径
    """
    print(f"🔍 视频超分: {video_path} -> {target_resolution}")
    
    # 1. 上传视频
    print("📤 上传视频...")
    video_url = upload_file(video_path)
    
    # 2. 提交任务
    print("📝 提交超分任务...")
    task = submit_upscale_task(video_url, target_resolution)
    
    # 3. 轮询结果
    print("⏳ 等待超分...")
    upscaled_url = poll_result(task["id"], task["urls"]["get"], max_attempts=120)
    
    # 4. 下载视频
    download_file(upscaled_url, output_path)
    
    return output_path


if __name__ == "__main__":
    # 测试
    print("="*50)
    print("视频生成核心模块测试")
    print("="*50)
    print(f"API Key: {API_KEY[:10]}...")
    print(f"Base URL: {BASE_URL}")
    print("✅ 模块加载成功")
