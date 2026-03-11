"""
飞书语音消息发送工具

使用示例:
    from skills.feishu_voice_sender import send_voice_message
    
    result = send_voice_message(
        audio_path="/tmp/voice.mp3",
        target_id="oc_xxx",
        target_type="chat"
    )
"""

from .feishu_voice_sender import (
    send_voice_message,
    send_voice,
    upload_voice,
    convert_to_amr,
    get_token,
    load_config
)

__all__ = [
    'send_voice_message',
    'send_voice',
    'upload_voice',
    'convert_to_amr',
    'get_token',
    'load_config'
]

__version__ = "1.0.0"
