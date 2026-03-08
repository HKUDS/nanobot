#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Media Hub - 媒体处理中心
处理、生成、发送、转换、编辑图片、音频、视频

与 Doc Hub 的关系：
- Media Hub 处理媒体文件（图片/音频/视频）
- Doc Hub 处理文档文件（Word/Excel/PDF/MD）
- 两者协作完成多媒体内容处理工作流
"""

import os
import sys
import subprocess
import json
import re
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass
from datetime import datetime

# 支持的格式
SUPPORTED_AUDIO_FORMATS = ['.mp3', '.wav', '.aac', '.flac', '.ogg', '.m4a', '.wma']
SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm', '.m4v', '.mpg', '.mpeg']
SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']


class MediaError(Exception):
    """媒体处理异常基类"""
    pass


class MediaConvertError(MediaError):
    """媒体转换异常"""
    pass


class MediaReadError(MediaError):
    """媒体读取异常"""
    pass


@dataclass
class MediaInfo:
    """媒体文件信息"""
    path: str
    media_type: str  # audio/video/image
    format: str
    size: int
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None


class MediaHub:
    """
    媒体处理中心
    
    核心能力：
    1. 格式转换（音频/视频/图片）
    2. 媒体信息提取
    3. 音频提取（从视频）
    4. 媒体编辑（裁剪、合并）
    5. 语音转文字（Whisper集成）
    """
    
    def __init__(self):
        self.workspace = Path('~/.nanobot/workspace')
        self.temp_dir = self.workspace / 'temp' / 'media_processing'
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 检查依赖
        self.deps = self._check_dependencies()
    
    def _check_dependencies(self) -> Dict[str, bool]:
        """检查必要的依赖"""
        deps = {
            'ffmpeg': False,
            'pydub': False,
            'moviepy': False,
            'whisper': False,
            'pillow': False
        }
        
        # 检查ffmpeg
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, timeout=5)
            deps['ffmpeg'] = result.returncode == 0
        except:
            pass
        
        # 检查Python库
        try:
            import pydub
            deps['pydub'] = True
        except ImportError:
            pass
        
        try:
            import moviepy
            deps['moviepy'] = True
        except ImportError:
            pass
        
        try:
            import whisper
            deps['whisper'] = True
        except ImportError:
            pass
        
        try:
            from PIL import Image
            deps['pillow'] = True
        except ImportError:
            pass
        
        return deps
    
    # ==================== 格式转换 ====================
    
    def convert_audio(self, input_path: str, output_path: str, **options) -> str:
        """
        转换音频格式
        
        Args:
            input_path: 输入音频文件路径
            output_path: 输出音频文件路径
            **options: 转换选项
                - bitrate: 比特率 (如 "128k", "192k", "320k")
                - sample_rate: 采样率 (如 44100, 48000, 16000)
                - channels: 声道数 (1=单声道, 2=立体声)
        
        Returns:
            输出文件的绝对路径
        """
        if not self.deps['ffmpeg']:
            raise MediaConvertError("ffmpeg未安装。请运行: brew install ffmpeg")
        
        input_path = Path(input_path)
        output_path = Path(output_path)
        
        print(f"🎵 转换音频: {input_path.name} -> {output_path.suffix}")
        
        # 构建ffmpeg命令
        cmd = ['ffmpeg', '-i', str(input_path), '-y']
        
        # 应用选项
        if 'sample_rate' in options:
            cmd.extend(['-ar', str(options['sample_rate'])])
        if 'channels' in options:
            cmd.extend(['-ac', str(options['channels'])])
        if 'bitrate' in options:
            cmd.extend(['-b:a', options['bitrate']])
        
        # 根据输出格式选择编码器
        if output_path.suffix == '.mp3':
            cmd.extend(['-c:a', 'libmp3lame'])
        elif output_path.suffix == '.aac':
            cmd.extend(['-c:a', 'aac'])
        elif output_path.suffix == '.wav':
            cmd.extend(['-c:a', 'pcm_s16le'])
        
        cmd.extend(['-loglevel', 'error', str(output_path)])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                print(f"✅ 音频转换成功: {output_path}")
                return str(output_path.absolute())
            else:
                raise MediaConvertError(f"转换失败: {result.stderr}")
        except Exception as e:
            raise MediaConvertError(f"转换错误: {str(e)}")
    
    def convert_video(self, input_path: str, output_path: str, **options) -> str:
        """
        转换视频格式
        
        Args:
            input_path: 输入视频文件路径
            output_path: 输出视频文件路径
            **options: 转换选项
                - fps: 帧率
                - resolution: 分辨率 (如 "1920x1080", "1280x720")
                - bitrate: 视频比特率
                - audio: 是否保留音频 (True/False)
                - codec: 视频编码器 (如 "libx264", "libx265")
        
        Returns:
            输出文件的绝对路径
        """
        if not self.deps['ffmpeg']:
            raise MediaConvertError("ffmpeg未安装。请运行: brew install ffmpeg")
        
        input_path = Path(input_path)
        output_path = Path(output_path)
        
        print(f"🎬 转换视频: {input_path.name} -> {output_path.suffix}")
        
        cmd = ['ffmpeg', '-i', str(input_path), '-y']
        
        # 视频选项
        if 'fps' in options:
            cmd.extend(['-r', str(options['fps'])])
        if 'resolution' in options:
            cmd.extend(['-s', options['resolution']])
        if 'bitrate' in options:
            cmd.extend(['-b:v', options['bitrate']])
        if 'codec' in options:
            cmd.extend(['-c:v', options['codec']])
        
        # 音频选项
        if options.get('audio') is False:
            cmd.extend(['-an'])
        
        cmd.extend(['-loglevel', 'error', str(output_path)])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                print(f"✅ 视频转换成功: {output_path}")
                return str(output_path.absolute())
            else:
                raise MediaConvertError(f"转换失败: {result.stderr}")
        except Exception as e:
            raise MediaConvertError(f"转换错误: {str(e)}")
    
    def convert_image(self, input_path: str, output_path: str, **options) -> str:
        """
        转换图片格式
        
        Args:
            input_path: 输入图片文件路径
            output_path: 输出图片文件路径
            **options: 转换选项
                - quality: 图片质量 (1-100，用于JPEG)
                - resize: 调整尺寸 (如 "800x600", "50%")
        
        Returns:
            输出文件的绝对路径
        """
        try:
            from PIL import Image
            
            input_path = Path(input_path)
            output_path = Path(output_path)
            
            print(f"🖼️  转换图片: {input_path.name} -> {output_path.suffix}")
            
            with Image.open(input_path) as img:
                # 调整尺寸
                if 'resize' in options:
                    resize = options['resize']
                    if '%' in resize:
                        ratio = int(resize.replace('%', '')) / 100
                        new_size = (int(img.width * ratio), int(img.height * ratio))
                    else:
                        new_size = tuple(map(int, resize.split('x')))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                # 保存
                save_kwargs = {}
                if output_path.suffix.lower() in ['.jpg', '.jpeg'] and 'quality' in options:
                    save_kwargs['quality'] = options['quality']
                    save_kwargs['optimize'] = True
                
                img.save(output_path, **save_kwargs)
            
            print(f"✅ 图片转换成功: {output_path}")
            return str(output_path.absolute())
            
        except ImportError:
            raise MediaConvertError("PIL未安装。请运行: pip install Pillow")
        except Exception as e:
            raise MediaConvertError(f"图片转换失败: {str(e)}")
    
    # ==================== 媒体信息提取 ====================
    
    def get_info(self, file_path: str) -> MediaInfo:
        """
        获取媒体文件信息
        
        Args:
            file_path: 媒体文件路径
        
        Returns:
            MediaInfo对象
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise MediaReadError(f"文件不存在: {file_path}")
        
        ext = file_path.suffix.lower()
        
        if ext in SUPPORTED_AUDIO_FORMATS:
            return self._get_audio_info(file_path)
        elif ext in SUPPORTED_VIDEO_FORMATS:
            return self._get_video_info(file_path)
        elif ext in SUPPORTED_IMAGE_FORMATS:
            return self._get_image_info(file_path)
        else:
            raise MediaReadError(f"不支持的格式: {ext}")
    
    def _get_audio_info(self, file_path: Path) -> MediaInfo:
        """获取音频信息"""
        try:
            from pydub import AudioSegment
            
            audio = AudioSegment.from_file(str(file_path))
            
            return MediaInfo(
                path=str(file_path.absolute()),
                media_type='audio',
                format=file_path.suffix.replace('.', ''),
                size=file_path.stat().st_size,
                duration_seconds=len(audio) / 1000,
                sample_rate=audio.frame_rate,
                channels=audio.channels
            )
        except ImportError:
            # 使用ffprobe作为后备
            return self._get_media_info_ffprobe(file_path, 'audio')
    
    def _get_video_info(self, file_path: Path) -> MediaInfo:
        """获取视频信息"""
        return self._get_media_info_ffprobe(file_path, 'video')
    
    def _get_image_info(self, file_path: Path) -> MediaInfo:
        """获取图片信息"""
        try:
            from PIL import Image
            
            with Image.open(file_path) as img:
                return MediaInfo(
                    path=str(file_path.absolute()),
                    media_type='image',
                    format=file_path.suffix.replace('.', ''),
                    size=file_path.stat().st_size,
                    width=img.width,
                    height=img.height
                )
        except ImportError:
            raise MediaReadError("PIL未安装。请运行: pip install Pillow")
    
    def _get_media_info_ffprobe(self, file_path: Path, media_type: str) -> MediaInfo:
        """使用ffprobe获取媒体信息"""
        try:
            cmd = [
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration,size:stream=codec_name,width,height,r_frame_rate,sample_rate,channels',
                '-of', 'json', str(file_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            
            format_info = data.get('format', {})
            streams = data.get('streams', [])
            
            # 提取信息
            duration = float(format_info.get('duration', 0)) if 'duration' in format_info else None
            size = int(format_info.get('size', 0))
            
            width = height = fps = sample_rate = channels = None
            for stream in streams:
                if stream.get('codec_type') == 'video':
                    width = stream.get('width')
                    height = stream.get('height')
                    fps_str = stream.get('r_frame_rate', '0/1')
                    fps = eval(fps_str) if '/' in fps_str else float(fps_str)
                elif stream.get('codec_type') == 'audio':
                    sample_rate = stream.get('sample_rate')
                    channels = stream.get('channels')
            
            return MediaInfo(
                path=str(file_path.absolute()),
                media_type=media_type,
                format=file_path.suffix.replace('.', ''),
                size=size,
                duration_seconds=duration,
                width=width,
                height=height,
                fps=fps,
                sample_rate=sample_rate,
                channels=channels
            )
            
        except Exception as e:
            raise MediaReadError(f"无法读取媒体信息: {str(e)}")
    
    # ==================== 音频提取与处理 ====================
    
    def extract_audio(self, video_path: str, output_path: str = None, **options) -> str:
        """
        从视频提取音频
        
        Args:
            video_path: 视频文件路径
            output_path: 输出音频路径（默认生成同名.wav）
            **options:
                - format: 输出格式 (wav/mp3/aac)
                - sample_rate: 采样率 (默认16000，Whisper推荐)
        
        Returns:
            音频文件路径
        """
        if not self.deps['ffmpeg']:
            raise MediaConvertError("ffmpeg未安装")
        
        video_path = Path(video_path)
        
        if not output_path:
            output_path = video_path.with_suffix('.wav')
        else:
            output_path = Path(output_path)
        
        print(f"🎵 从视频提取音频: {video_path.name}")
        
        # Whisper优化参数
        format_ext = options.get('format', 'wav')
        sample_rate = options.get('sample_rate', 16000)
        
        cmd = [
            'ffmpeg', '-i', str(video_path),
            '-vn',  # 禁用视频
            '-acodec', 'pcm_s16le' if format_ext == 'wav' else 'libmp3lame',
            '-ar', str(sample_rate),
            '-ac', '1',  # 单声道
            str(output_path),
            '-y', '-loglevel', 'error'
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                print(f"✅ 音频提取成功: {output_path}")
                return str(output_path.absolute())
            else:
                raise MediaConvertError(f"提取失败: {result.stderr}")
        except Exception as e:
            raise MediaConvertError(f"提取错误: {str(e)}")
    
    def trim_media(self, input_path: str, output_path: str, start_time: float, end_time: float) -> str:
        """
        裁剪媒体文件
        
        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
        
        Returns:
            输出文件路径
        """
        if not self.deps['ffmpeg']:
            raise MediaConvertError("ffmpeg未安装")
        
        print(f"✂️  裁剪媒体: {start_time}s - {end_time}s")
        
        cmd = [
            'ffmpeg', '-i', str(input_path),
            '-ss', str(start_time),
            '-t', str(end_time - start_time),
            '-c', 'copy',
            str(output_path),
            '-y', '-loglevel', 'error'
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                print(f"✅ 裁剪成功: {output_path}")
                return str(output_path)
            else:
                raise MediaConvertError(f"裁剪失败: {result.stderr}")
        except Exception as e:
            raise MediaConvertError(f"裁剪错误: {str(e)}")
    
    def merge_audio_video(self, video_path: str, audio_path: str, output_path: str) -> str:
        """
        合并视频和音频
        
        Args:
            video_path: 视频文件路径
            audio_path: 音频文件路径
            output_path: 输出视频路径
        
        Returns:
            输出文件路径
        """
        if not self.deps['ffmpeg']:
            raise MediaConvertError("ffmpeg未安装")
        
        print(f"🔗 合并音视频...")
        
        cmd = [
            'ffmpeg', '-i', str(video_path), '-i', str(audio_path),
            '-c:v', 'copy', '-c:a', 'aac', '-shortest',
            str(output_path),
            '-y', '-loglevel', 'error'
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                print(f"✅ 合并成功: {output_path}")
                return str(output_path)
            else:
                raise MediaConvertError(f"合并失败: {result.stderr}")
        except Exception as e:
            raise MediaConvertError(f"合并错误: {str(e)}")
    
    # ==================== 语音转文字 ====================
    
    def transcribe(self, audio_path: str, model_size: str = "base", 
                   language: str = "zh", verbose: bool = False) -> Dict[str, Any]:
        """
        使用Whisper转录音频
        
        Args:
            audio_path: 音频文件路径
            model_size: 模型大小 (tiny/base/small/medium/large)
            language: 语言代码 (zh/en/auto)
            verbose: 是否显示详细进度
        
        Returns:
            转录结果字典
        """
        if not self.deps['whisper']:
            raise MediaError("Whisper未安装。请运行: pip install openai-whisper")
        
        import whisper
        import warnings
        warnings.filterwarnings('ignore')
        
        print(f"🎯 加载Whisper模型: {model_size}")
        model = whisper.load_model(model_size)
        
        print(f"📝 开始转录...")
        result = model.transcribe(
            str(audio_path),
            language=language if language != 'auto' else None,
            verbose=verbose
        )
        
        print(f"✅ 转录完成: {len(result['text'])} 字符")
        return result
    
    def transcribe_video(self, video_path: str, model_size: str = "base",
                         language: str = "zh") -> Dict[str, Any]:
        """
        转录视频中的音频（自动提取+转录）
        
        Args:
            video_path: 视频文件路径
            model_size: 模型大小
            language: 语言
        
        Returns:
            包含transcript/text的完整结果
        """
        # 创建临时音频文件
        temp_audio = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_audio_path = temp_audio.name
        temp_audio.close()
        
        try:
            # 提取音频
            self.extract_audio(video_path, temp_audio_path, format='wav', sample_rate=16000)
            
            # 转录
            result = self.transcribe(temp_audio_path, model_size, language)
            
            return result
            
        finally:
            # 清理临时文件
            if os.path.exists(temp_audio_path):
                os.unlink(temp_audio_path)
    
    # ==================== 与Doc Hub的协作接口 ====================
    
    def convert_to_doc_format(self, media_path: str, output_format: str = "txt") -> str:
        """
        将媒体内容转换为文档格式（供Doc Hub使用）
        
        Args:
            media_path: 媒体文件路径
            output_format: 输出格式 (txt/md/json)
        
        Returns:
            输出文件路径
        """
        media_path = Path(media_path)
        
        if media_path.suffix.lower() in SUPPORTED_VIDEO_FORMATS:
            # 视频：提取音频 → 转录 → 保存为文本
            result = self.transcribe_video(str(media_path))
            
            if output_format == 'json':
                output_path = media_path.with_suffix('.json')
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
            else:
                output_path = media_path.with_suffix('.txt')
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result['text'])
            
            return str(output_path)
        
        elif media_path.suffix.lower() in SUPPORTED_AUDIO_FORMATS:
            # 音频：直接转录
            result = self.transcribe(str(media_path))
            
            output_path = media_path.with_suffix('.txt')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result['text'])
            
            return str(output_path)
        
        else:
            raise MediaError(f"不支持的媒体格式: {media_path.suffix}")


# ==================== 便捷函数 ====================

def get_hub() -> MediaHub:
    """获取MediaHub实例"""
    return MediaHub()


def convert_audio(input_path: str, output_path: str, **options) -> str:
    """转换音频格式"""
    return get_hub().convert_audio(input_path, output_path, **options)


def convert_video(input_path: str, output_path: str, **options) -> str:
    """转换视频格式"""
    return get_hub().convert_video(input_path, output_path, **options)


def extract_audio(video_path: str, output_path: str = None, **options) -> str:
    """从视频提取音频"""
    return get_hub().extract_audio(video_path, output_path, **options)


def transcribe(audio_path: str, model_size: str = "base", language: str = "zh") -> str:
    """转录音频为文本"""
    result = get_hub().transcribe(audio_path, model_size, language)
    return result['text']


def get_info(file_path: str) -> MediaInfo:
    """获取媒体文件信息"""
    return get_hub().get_info(file_path)


# ==================== 版本信息 ====================

__version__ = "1.0.0"
__all__ = [
    'MediaHub', 'MediaInfo', 'MediaError', 'MediaConvertError', 'MediaReadError',
    'get_hub', 'convert_audio', 'convert_video', 'extract_audio', 
    'transcribe', 'get_info', 'SUPPORTED_AUDIO_FORMATS', 'SUPPORTED_VIDEO_FORMATS'
]


if __name__ == "__main__":
    print("🎬 Media Hub - 媒体处理中心")
    print("=" * 60)
    
    hub = get_hub()
    
    print("\n依赖检查:")
    for dep, available in hub.deps.items():
        status = "✅" if available else "❌"
        print(f"  {status} {dep}")
    
    print("\n支持格式:")
    print(f"  音频: {', '.join(SUPPORTED_AUDIO_FORMATS)}")
    print(f"  视频: {', '.join(SUPPORTED_VIDEO_FORMATS)}")
    print(f"  图片: {', '.join(SUPPORTED_IMAGE_FORMATS)}")
    
    print("\n" + "=" * 60)
    print("与Doc Hub协作: media.convert_to_doc_format(video_path) -> txt/json")
