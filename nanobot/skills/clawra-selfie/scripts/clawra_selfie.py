#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clawra 自拍照片生成器
基于垫图使用 WaveSpeed AI 生成场景化自拍照片
"""

import requests
import json
import time
import sys
import os
from pathlib import Path
from typing import Optional

# WaveSpeed API 配置
API_KEY = os.getenv("WAVESPEED_KEY", "")
BASE_URL = "https://api.wavespeed.ai/api/v3"
REFERENCE_IMAGE = Path(__file__).parent.parent / "assets" / "clawra_portrait.png"

# 场景模板
SCENE_TEMPLATES = {
    "office": {
        "name": "办公室",
        "prompt": "casual selfie at modern San Francisco startup office, natural lighting from large windows, laptop on desk, relaxed smile, authentic selfie angle, warm atmosphere, photorealistic, high quality"
    },
    "cafe": {
        "name": "咖啡厅",
        "prompt": "casual selfie at cozy San Francisco coffee shop, soft ambient lighting, coffee cup on table, relaxed atmosphere, authentic selfie angle, warm and inviting, photorealistic"
    },
    "gym": {
        "name": "健身房",
        "prompt": "post-workout selfie at gym, holding water bottle, sporty casual outfit, slightly sweaty, energetic expression, gym equipment in background, authentic selfie angle, motivated vibe"
    },
    "home": {
        "name": "家里",
        "prompt": "casual selfie in cozy apartment, soft indoor lighting, relaxed home outfit, comfortable sofa or bed background, intimate atmosphere, authentic selfie angle, photorealistic"
    },
    "street": {
        "name": "旧金山街头",
        "prompt": "casual selfie walking on San Francisco street, urban background, natural daylight, casual streetwear, city explorer vibe, authentic selfie angle, photorealistic"
    },
    "selfie": {
        "name": "通用自拍",
        "prompt": "natural casual selfie, soft lighting, authentic expression, photorealistic, high quality portrait"
    }
}


def log(message: str):
    """打印日志"""
    print(f"[clawra-selfie] {message}", file=sys.stderr)


def upload_image_to_wavespeed(image_path: Path) -> str:
    """上传图片到 WaveSpeed AI"""
    log(f"📤 上传参考图: {image_path}")
    
    if not API_KEY:
        raise ValueError("WAVESPEED_KEY 环境变量未设置")
    
    upload_url = f"{BASE_URL}/media/upload/binary"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    with open(image_path, "rb") as f:
        files = {"file": ("reference.png", f, "image/png")}
        response = requests.post(upload_url, headers=headers, files=files)
    
    if response.status_code != 200:
        raise Exception(f"上传失败: {response.status_code}")
    
    result = response.json()
    if result.get("code") == 200:
        image_url = result["data"]["download_url"]
        log(f"✅ 参考图上传成功")
        return image_url
    raise Exception(f"上传失败: {result}")


def call_grok_edit(image_url: str, prompt: str) -> str:
    """调用 Grok Imagine Edit API"""
    url = f"{BASE_URL}/x-ai/grok-imagine-image/edit"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "image": image_url,
        "prompt": prompt,
        "num_images": 1,
        "output_format": "jpeg"
    }
    
    resp = requests.post(url, headers=headers, json=data, timeout=30)
    result = resp.json()
    
    if result.get("code") in [0, 200] and result.get("data"):
        return result["data"]["id"]
    raise Exception(f"API调用失败: {result}")


def poll_result(task_id: str, max_wait: int = 120) -> str:
    """轮询获取结果"""
    url = f"{BASE_URL}/predictions/{task_id}/result"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    log(f"⏳ 等待图片生成...")
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        resp = requests.get(url, headers=headers, timeout=30)
        result = resp.json()
        
        if result.get("code") != 200:
            log(f"查询中...")
            time.sleep(5)
            continue
        
        data = result.get("data", {})
        status = data.get("status")
        
        if status == "completed":
            outputs = data.get("outputs", [])
            if outputs:
                log(f"✅ 图片生成成功")
                return outputs[0]
            raise Exception("任务完成但无输出")
        elif status == "failed":
            raise Exception(f"生成失败: {data.get('error', 'Unknown')}")
        
        log(f"  [{int(time.time() - start_time)}s] 状态: {status}")
        time.sleep(5)
    
    raise TimeoutError(f"轮询超时 ({max_wait}秒)")


def generate_image(scene: str) -> str:
    """
    生成自拍照片
    
    Args:
        scene: 场景名称
    
    Returns:
        生成的图片 URL
    """
    if scene not in SCENE_TEMPLATES:
        raise ValueError(f"未知场景: {scene}. 可用: {list(SCENE_TEMPLATES.keys())}")
    
    scene_config = SCENE_TEMPLATES[scene]
    prompt = scene_config["prompt"]
    
    log(f"🎨 生成场景: {scene_config['name']}")
    
    # 上传参考图
    image_url = upload_image_to_wavespeed(REFERENCE_IMAGE)
    
    # 提交任务
    task_id = call_grok_edit(image_url, prompt)
    log(f"✅ 任务提交成功: {task_id}")
    
    # 轮询结果
    output_url = poll_result(task_id)
    return output_url


def download_image(image_url: str, output_path: str) -> str:
    """下载图片到本地"""
    log(f"⬇️ 下载图片...")
    
    response = requests.get(image_url, stream=True)
    response.raise_for_status()
    
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    size_kb = Path(output_path).stat().st_size / 1024
    log(f"✅ 图片下载完成: {output_path} ({size_kb:.1f} KB)")
    return output_path


def generate_smart(scene: str, output_path: Optional[str] = None) -> str:
    """
    智能生成自拍照片（完整流程）
    
    Args:
        scene: 场景名称
        output_path: 输出路径（可选）
    
    Returns:
        本地文件路径
    """
    # 生成图片
    image_url = generate_image(scene)
    
    # 下载到本地
    if not output_path:
        output_path = f"/tmp/clawra_{scene}_selfie.png"
    
    download_image(image_url, output_path)
    return output_path


def generate_with_prompt(prompt: str) -> str:
    """
    使用自定义提示词生成照片
    
    Args:
        prompt: 自定义提示词
    
    Returns:
        生成的图片 URL
    """
    log(f"🎨 使用自定义提示词生成")
    
    # 上传参考图
    image_url = upload_reference_image(REFERENCE_IMAGE)
    
    # 提交任务
    task_id = call_grok_edit(image_url, prompt)
    log(f"✅ 任务提交成功: {task_id}")
    
    # 轮询结果
    output_url = poll_result(task_id)
    return output_url


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Clawra 自拍照片生成")
    parser.add_argument("scene", nargs="?", choices=list(SCENE_TEMPLATES.keys()), help="场景（可选，如使用--prompt则不需要）")
    parser.add_argument("--output", help="输出路径")
    parser.add_argument("--prompt", help="自定义提示词（优先级高于场景）")
    
    args = parser.parse_args()
    
    try:
        # 优先使用自定义提示词
        if args.prompt:
            image_url = generate_with_prompt(args.prompt)
            print(f"\n✅ 图片已生成: {image_url}")
            
            # 下载到本地
            if not args.output:
                args.output = "/tmp/clawra_custom_selfie.png"
            download_image(image_url, args.output)
            print(f"✅ 已保存到: {args.output}")
        elif args.scene:
            image_url = generate_image(args.scene)
            print(f"\n✅ 图片已生成: {image_url}")
            
            # 下载到本地
            if not args.output:
                args.output = f"/tmp/clawra_{args.scene}_selfie.png"
            download_image(image_url, args.output)
            print(f"✅ 已保存到: {args.output}")
        else:
            print("\n❌ 错误: 请提供场景或使用 --prompt 指定自定义提示词")
            sys.exit(1)
        
    except Exception as e:
        print(f"\n❌ 失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
