#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书视频发送工具 - 直接调用API发送视频消息

使用方式:
    python3 feishu_video_sender.py <视频路径> <目标ID> [封面图路径] [消息文案]

示例:
    python3 feishu_video_sender.py /path/to/video.mp4 ou_xxx
    python3 feishu_video_sender.py /path/to/video.mp4 oc_xxx /path/to/cover.jpg "视频描述"
"""

import requests
import json
import sys
import os
import subprocess
from pathlib import Path

APP_ID = os.getenv("NANOBOT_CHANNELS__FEISHU__APP_ID")
APP_SECRET = os.getenv("NANOBOT_CHANNELS__FEISHU__APP_SECRET")


def get_token():
    """获取 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET})
    result = resp.json()
    if result.get("code") == 0:
        return result["tenant_access_token"]
    raise Exception(f"获取token失败: {result}")


def upload_video(video_path, token):
    """上传视频文件，返回 file_key"""
    url = "https://open.feishu.cn/open-apis/im/v1/files"
    headers = {"Authorization": f"Bearer {token}"}
    
    with open(video_path, "rb") as f:
        files = {"file": (Path(video_path).name, f, "video/mp4")}
        data = {"file_type": "mp4", "file_name": Path(video_path).name}
        resp = requests.post(url, headers=headers, files=files, data=data)
    
    result = resp.json()
    if result.get("code") == 0:
        return result["data"]["file_key"]
    raise Exception(f"视频上传失败: {result}")


def upload_image(image_path, token):
    """上传图片，返回 image_key"""
    url = "https://open.feishu.cn/open-apis/im/v1/images"
    headers = {"Authorization": f"Bearer {token}"}
    
    with open(image_path, "rb") as f:
        files = {"image": (Path(image_path).name, f, "image/jpeg")}
        data = {"image_type": "message"}
        resp = requests.post(url, headers=headers, files=files, data=data)
    
    result = resp.json()
    if result.get("code") == 0:
        return result["data"]["image_key"]
    raise Exception(f"封面上传失败: {result}")


def generate_cover(video_path, output_path):
    """从视频生成封面图（第1秒的画面）"""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-ss", "00:00:01",
        "-vframes", "1",
        output_path,
        "-y"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"封面生成失败: {result.stderr}")
    return output_path


def send_video(file_key, image_key, target_id, token, msg_type="open_id"):
    """发送视频消息"""
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={msg_type}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    payload = {
        "receive_id": target_id,
        "msg_type": "media",
        "content": json.dumps({
            "file_key": file_key,
            "image_key": image_key
        })
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    result = resp.json()
    
    if result.get("code") == 0:
        return result["data"]["message_id"]
    raise Exception(f"发送失败: {result}")


def main():
    if len(sys.argv) < 3:
        print("用法: python3 feishu_video_sender.py <视频路径> <目标ID> [封面图路径] [消息文案]")
        print("目标ID示例: ou_xxx (用户) 或 oc_xxx (群聊)")
        sys.exit(1)
    
    video_path = sys.argv[1]
    target_id = sys.argv[2]
    cover_path = sys.argv[3] if len(sys.argv) > 3 else None
    caption = sys.argv[4] if len(sys.argv) > 4 else ""
    
    # 判断目标类型
    if target_id.startswith("ou_"):
        msg_type = "open_id"
    elif target_id.startswith("oc_"):
        msg_type = "chat_id"
    else:
        print("错误: 目标ID格式不正确，应以 ou_ 或 oc_ 开头")
        sys.exit(1)
    
    try:
        print("🔑 获取token...")
        token = get_token()
        
        print("📤 上传视频...")
        file_key = upload_video(video_path, token)
        print(f"   file_key: {file_key[:40]}...")
        
        if cover_path:
            print("📤 上传封面...")
            image_key = upload_image(cover_path, token)
        else:
            print("🖼️ 生成封面...")
            temp_cover = "/tmp/video_cover.jpg"
            generate_cover(video_path, temp_cover)
            image_key = upload_image(temp_cover, token)
        print(f"   image_key: {image_key[:40]}...")
        
        print("📨 发送视频...")
        message_id = send_video(file_key, image_key, target_id, token, msg_type)
        
        print(f"\n✅ 发送成功!")
        print(f"消息ID: {message_id}")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
