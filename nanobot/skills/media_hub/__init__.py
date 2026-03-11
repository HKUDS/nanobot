"""
Media Hub - 媒体处理中心

整合音视频处理、转录、转换、TTS功能。

目录结构:
- media_hub.py: 核心媒体处理（格式转换、信息提取）
- video_understanding.py: 视频/音频理解（飞书集成、转录分析）
- tts.py: 文字转语音（Edge TTS）
"""

from .media_hub import (
    MediaHub, MediaInfo, MediaError, MediaConvertError, MediaReadError,
    get_hub, convert_audio, convert_video, extract_audio,
    transcribe, get_info, SUPPORTED_AUDIO_FORMATS, SUPPORTED_VIDEO_FORMATS
)

# 视频理解功能
from .video_understanding import (
    VideoUnderstandingSkill,
    process_video,
    process_podcast,
    transcribe_audio,
)

# TTS功能（可选）
try:
    from .tts import (
        text_to_speech,
        tts_xiaoxiao,
        tts_yunjian,
        tts_xiaoyi,
        list_voices,
    )
    _TTS_AVAILABLE = True
except ImportError:
    _TTS_AVAILABLE = False
    print("⚠️  TTS功能不可用，请安装: pip install edge-tts")

__version__ = "1.0.0"
__all__ = [
    # 核心媒体处理
    'MediaHub', 'MediaInfo', 'MediaError', 'MediaConvertError', 'MediaReadError',
    'get_hub', 'convert_audio', 'convert_video', 'extract_audio',
    'transcribe', 'get_info',
    # 视频理解
    'VideoUnderstandingSkill', 'process_video', 'process_podcast', 'transcribe_audio',
    # TTS
    'text_to_speech', 'tts_xiaoxiao', 'tts_yunjian', 'tts_xiaoyi', 'list_voices',
    # 常量
    'SUPPORTED_AUDIO_FORMATS', 'SUPPORTED_VIDEO_FORMATS'
]

def get_media_hub():
    """获取MediaHub实例（基础媒体处理）"""
    return MediaHub()

def get_video_understanding():
    """获取VideoUnderstandingSkill实例（高级视频理解）"""
    return VideoUnderstandingSkill()
