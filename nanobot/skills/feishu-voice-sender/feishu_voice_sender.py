#!/usr/bin/env python3
"""
飞书语音消息发送工具
将 MP3 音频以语音条形式发送到飞书
"""

import requests
import json
import os
import sys
import subprocess
import tempfile
from pathlib import Path

def load_config():
    """从系统环境变量加载飞书凭据"""
    config = {
        'FEISHU_APP_ID': os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_ID', ''),
        'FEISHU_APP_SECRET': os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_SECRET', ''),
    }
    if not config['FEISHU_APP_ID'] or not config['FEISHU_APP_SECRET']:
        raise Exception("缺少飞书凭据，请设置环境变量 NANOBOT_CHANNELS__FEISHU__APP_ID / NANOBOT_CHANNELS__FEISHU__APP_SECRET")
    return config


def get_token(config):
    """获取 tenant_access_token"""
    app_id = config.get('FEISHU_APP_ID')
    app_secret = config.get('FEISHU_APP_SECRET')
    
    if not app_id or not app_secret:
        raise Exception("缺少飞书配置，请检查 ~/.nanobot/config/main.env")
    
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    result = resp.json()
    
    if result.get("code") == 0:
        return result["tenant_access_token"]
    raise Exception(f"获取token失败: {result}")


def convert_to_amr(input_path, output_path):
    """将音频转换为飞书语音格式（MP3）"""
    # 飞书语音消息支持 MP3，直接复制或转换
    cmd = [
        'ffmpeg', '-y',
        '-i', input_path,
        '-ar', '16000',      # 采样率 16kHz
        '-ac', '1',          # 单声道
        '-b:a', '24k',       # 比特率
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # 如果转换失败，直接复制原文件
        import shutil
        shutil.copy(input_path, output_path)
    
    return output_path


def upload_voice(file_path, token):
    """上传语音文件，返回 file_key"""
    url = "https://open.feishu.cn/open-apis/im/v1/files"
    
    headers = {"Authorization": f"Bearer {token}"}
    
    with open(file_path, 'rb') as f:
        files = {"file": (Path(file_path).name, f, "audio/mpeg")}
        # file_type 必须是 "opus" 才能上传音频文件
        data = {"file_type": "opus", "file_name": Path(file_path).name}
        resp = requests.post(url, headers=headers, files=files, data=data)
    
    result = resp.json()
    if result.get("code") == 0:
        return result["data"]["file_key"]
    raise Exception(f"上传语音失败: {result}")


def send_voice(file_key, target_id, token, target_type="chat"):
    """发送语音消息"""
    receive_id_type = "chat_id" if target_type == "chat" else "open_id"
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    payload = {
        "receive_id": target_id,
        "msg_type": "audio",  # 正确的消息类型是 audio
        "content": json.dumps({
            "file_key": file_key
        })
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    result = resp.json()
    
    if result.get("code") == 0:
        return result["data"]["message_id"]
    raise Exception(f"发送语音失败: {result}")


def send_voice_message(audio_path, target_id, target_type="chat"):
    """
    发送语音消息的完整流程
    
    Args:
        audio_path: MP3 音频文件路径
        target_id: 目标ID（群ID或用户ID）
        target_type: "chat" 或 "user"
    
    Returns:
        {"message_id": "...", "file_key": "..."}
    """
    # 1. 加载小爪的配置
    config = load_config()
    token = get_token(config)
    
    # 2. 转换为 AMR
    with tempfile.NamedTemporaryFile(suffix='.amr', delete=False) as tmp:
        amr_path = tmp.name
    
    try:
        print(f"🎵 转换音频格式...")
        convert_to_amr(audio_path, amr_path)
        
        # 3. 上传语音
        print(f"📤 上传语音...")
        file_key = upload_voice(amr_path, token)
        
        # 4. 发送消息
        print(f"📨 发送语音消息...")
        message_id = send_voice(file_key, target_id, token, target_type)
        
        return {
            "message_id": message_id,
            "file_key": file_key,
            "success": True
        }
    
    finally:
        # 清理临时文件
        if os.path.exists(amr_path):
            os.unlink(amr_path)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='发送飞书语音消息')
    parser.add_argument('audio_path', help='MP3音频文件路径')
    parser.add_argument('target_id', help='目标ID')
    parser.add_argument('--chat', action='store_true', help='发送到群聊')
    parser.add_argument('--user', action='store_true', help='发送到私聊')
    
    args = parser.parse_args()
    
    target_type = "user" if args.user else "chat"
    
    try:
        result = send_voice_message(args.audio_path, args.target_id, target_type)
        print(f"✅ 发送成功: {result['message_id']}")
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        sys.exit(1)
