#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clawra 自拍视频生成器
基于垫图使用 WaveSpeed AI 生成场景化动态自拍视频
"""

import requests
import json
import time
import sys
import os
from pathlib import Path

# WaveSpeed API 配置
API_KEY = os.getenv("WAVESPEED_KEY", "")
API_BASE = "https://api.wavespeed.ai/api/v3"
REFERENCE_IMAGE = Path(__file__).parent.parent / "assets" / "clawra_portrait.png"

# 场景模板
SCENE_TEMPLATES = {
    "office": {
        "name": "办公室",
        "prompt": "A young woman taking a selfie video in a modern San Francisco startup office, natural lighting from large windows, casual professional outfit, slight natural movement, authentic selfie angle, warm atmosphere, high quality"
    },
    "cafe": {
        "name": "咖啡厅", 
        "prompt": "A young woman taking a selfie video at a cozy coffee shop in San Francisco, soft natural lighting, casual outfit, holding a coffee cup, slight natural movement, authentic selfie angle, warm and relaxed atmosphere, high quality"
    },
    "gym": {
        "name": "健身房",
        "prompt": "A young woman taking a selfie video at the gym after workout, holding water bottle, sporty outfit, energetic expression, slight natural movement, authentic selfie angle, motivated atmosphere, high quality"
    },
    "home": {
        "name": "家里",
        "prompt": "A young woman taking a selfie video in her cozy apartment, casual home outfit, soft indoor lighting, relaxed expression, slight natural movement, authentic selfie angle, intimate atmosphere, high quality"
    },
    "street": {
        "name": "旧金山街头",
        "prompt": "A young woman taking a selfie video walking on San Francisco street, casual streetwear, urban background, natural daylight, slight natural movement, authentic selfie angle, city explorer vibe, high quality"
    }
}


def log(msg):
    """打印日志"""
    print(f"[clawra-video-selfie] {msg}")


def upload_reference_image(image_path):
    """上传参考图到 WaveSpeed AI"""
    log(f"📤 上传参考图: {image_path}")
    
    if not API_KEY:
        raise ValueError("WAVESPEED_KEY 环境变量未设置")
    
    url = f"{API_BASE}/media/upload/binary"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    with open(image_path, "rb") as f:
        files = {"file": ("reference.png", f, "image/png")}
        resp = requests.post(url, headers=headers, files=files)
    
    if resp.status_code != 200:
        raise Exception(f"上传失败: {resp.status_code} - {resp.text[:200]}")
    
    result = resp.json()
    if result.get("code") == 200:
        image_url = result["data"]["download_url"]
        log(f"✅ 参考图上传成功")
        return image_url
    raise Exception(f"上传失败: {result}")


def generate_video_task(image_url, prompt, duration=5):
    """提交视频生成任务"""
    log(f"🎬 提交视频生成任务 (时长: {duration}秒)...")
    
    endpoint = f"{API_BASE}/wavespeed-ai/wan-2.2/i2v-480p"
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "image": image_url,
        "prompt": prompt,
        "duration": duration,
        "enable_prompt_expansion": False
    }
    
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
    result = resp.json()
    
    if result.get("code") == 200:
        task_id = result["data"]["id"]
        log(f"✅ 任务提交成功: {task_id}")
        return task_id
    raise Exception(f"提交失败: {result}")


def poll_task_result(task_id, timeout=300):
    """轮询任务结果"""
    log(f"⏳ 等待视频生成 (最长{timeout}秒)...")
    
    result_url = f"{API_BASE}/predictions/{task_id}/result"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        resp = requests.get(result_url, headers=headers)
        result = resp.json()
        
        if result.get("code") != 200:
            log(f"查询失败: {result.get('message')}")
            time.sleep(5)
            continue
        
        data = result["data"]
        status = data.get("status")
        elapsed = int(time.time() - start_time)
        
        if status == "completed":
            outputs = data.get("outputs", [])
            if outputs:
                video_url = outputs[0]
                log(f"✅ 视频生成完成")
                return video_url
            else:
                raise Exception("任务完成但无输出")
        
        elif status == "failed":
            error = data.get("error", "Unknown error")
            raise Exception(f"视频生成失败: {error}")
        
        log(f"  [{elapsed}s] 状态: {status}")
        time.sleep(10)
    
    raise TimeoutError("视频生成超时")


def download_video(video_url, output_path):
    """下载视频到本地"""
    log(f"⬇️ 下载视频...")
    
    resp = requests.get(video_url, stream=True)
    resp.raise_for_status()
    
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    
    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    log(f"✅ 视频下载完成: {output_path} ({size_mb:.1f} MB)")


def generate_video(scene, duration=5, output_path=None, ref_image=None):
    """
    生成自拍视频
    
    Args:
        scene: 场景名称 (office/cafe/gym/home/street)
        duration: 视频时长 (秒)，只能是 5 或 8
        output_path: 输出路径
        ref_image: 自定义参考图路径 (可选)
    
    Returns:
        输出文件路径
    """
    # API 只支持 5 或 8 秒
    if duration not in [5, 8]:
        duration = 5
        log(f"⚠️ 时长调整为 5 秒 (API 只支持 5 或 8 秒)")
    
    if scene not in SCENE_TEMPLATES:
        raise ValueError(f"未知场景: {scene}. 可用: {list(SCENE_TEMPLATES.keys())}")
    
    scene_config = SCENE_TEMPLATES[scene]
    prompt = scene_config['prompt']
    
    log(f"🎬 开始生成场景: {scene_config['name']}, 时长: {duration}秒")
    
    # 使用自定义垫图或默认垫图
    image_path = Path(ref_image) if ref_image else REFERENCE_IMAGE
    
    try:
        # 1. 上传参考图
        image_url = upload_reference_image(image_path)
        
        # 2. 提交视频生成任务
        task_id = generate_video_task(image_url, prompt, duration)
        
        # 3. 轮询结果
        video_url = poll_task_result(task_id)
        
        # 4. 下载视频
        if not output_path:
            output_path = f"/tmp/clawra_{scene}_video.mp4"
        
        download_video(video_url, output_path)
        
        log(f"✅ 全部完成: {output_path}")
        return output_path
        
    except Exception as e:
        log(f"❌ 生成失败: {e}")
        raise
        raise ValueError(f"未知场景: {scene}. 可用: {list(SCENE_TEMPLATES.keys())}")
    
    scene_config = SCENE_TEMPLATES[scene]
    prompt = scene_config['prompt']
    
    log(f"🎬 开始生成场景: {scene_config['name']}, 时长: {duration}秒")
    
    try:
        # 1. 上传参考图
        image_url = upload_reference_image(REFERENCE_IMAGE)
        
        # 2. 提交视频生成任务
        task_id = generate_video_task(image_url, prompt, duration)
        
        # 3. 轮询结果
        video_url = poll_task_result(task_id)
        
        # 4. 下载视频
        if not output_path:
            output_path = f"/tmp/clawra_{scene}_video.mp4"
        
        download_video(video_url, output_path)
        
        log(f"✅ 全部完成: {output_path}")
        return output_path
        
    except Exception as e:
        log(f"❌ 生成失败: {e}")
        raise


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Clawra 视频自拍生成')
    parser.add_argument('scene', choices=list(SCENE_TEMPLATES.keys()), help='场景')
    parser.add_argument('--duration', type=int, default=5, choices=[5, 8], help='时长(秒)，可选 5 或 8')
    parser.add_argument('--output', help='输出路径')
    parser.add_argument('--ref', help='自定义参考图路径')
    
    args = parser.parse_args()
    
    try:
        output = generate_video(args.scene, args.duration, args.output, args.ref)
        print(f"\n✅ 视频已生成: {output}")
    except Exception as e:
        print(f"\n❌ 失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
