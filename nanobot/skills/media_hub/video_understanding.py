#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Video Understanding Skill - 音视频理解技能
基于本地Whisper模型，无需OpenAI API

功能：
1. 下载群聊视频/音频文件
2. 提取音频轨道（ffmpeg）
3. 本地Whisper语音转文字
4. 文本理解与分析
5. 生成结构化纪要

使用场景：
- 群聊视频理解
- 播客音频转录
- 会议录音整理
- 短视频内容提取
"""

import os
import sys
import subprocess
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

# 添加项目路径
sys.path.insert(0, '~/.hiperone/workspace')

class VideoUnderstandingSkill:
    """音视频理解技能 - 统一入口"""
    
    # 支持的音频/视频格式
    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv'}
    AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.wma'}
    
    def __init__(self, temp_dir: str = None):
        self.workspace = Path('~/.hiperone/workspace')
        self.temp_dir = Path(temp_dir) if temp_dir else self.workspace / 'temp' / 'video_processing'
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        self.feishu_app_id = os.getenv("NANOBOT_CHANNELS__FEISHU__APP_ID")
        self.feishu_app_secret = os.getenv("NANOBOT_CHANNELS__FEISHU__APP_SECRET")
        
        # 检查依赖
        self.deps = self._check_dependencies()
    
    def _check_dependencies(self) -> Dict[str, bool]:
        """检查必要的依赖"""
        deps = {'ffmpeg': False, 'whisper': False}
        
        # 检查ffmpeg
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, timeout=5)
            deps['ffmpeg'] = result.returncode == 0
        except:
            pass
        
        # 检查whisper
        try:
            import whisper
            deps['whisper'] = True
        except ImportError:
            pass
        
        return deps
    
    # ==================== 下载功能 ====================
    
    def download_from_feishu(self, message_id: str, file_key: str, 
                            file_name: str = None) -> Optional[Path]:
        """
        从飞书群聊下载视频/音频文件
        
        Args:
            message_id: 消息ID
            file_key: 文件key
            file_name: 保存的文件名
            
        Returns:
            下载的文件路径
        """
        import requests
        
        # 获取token
        token = self._get_feishu_token()
        if not token:
            return None
        
        # 使用message-resource API下载
        resource_url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}?type=file"
        headers = {"Authorization": f"Bearer {token}"}
        
        print(f"📥 下载文件: {file_name or 'unknown'}")
        r = requests.get(resource_url, headers=headers, timeout=120)
        
        if r.status_code != 200:
            print(f"❌ 下载失败: {r.status_code} - {r.text[:200]}")
            return None
        
        # 确定文件扩展名
        if not file_name:
            content_type = r.headers.get('content-type', '')
            if 'video' in content_type:
                ext = '.mp4'
            elif 'audio' in content_type:
                ext = '.m4a'
            else:
                ext = '.bin'
            file_name = f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        
        output_path = self.temp_dir / file_name
        with open(output_path, 'wb') as f:
            f.write(r.content)
        
        print(f"✅ 下载成功: {output_path.name} ({len(r.content) / 1024 / 1024:.2f} MB)")
        return output_path
    
    def download_from_url(self, url: str, file_name: str = None) -> Optional[Path]:
        """
        从URL下载音频/视频文件
        
        Args:
            url: 文件URL
            file_name: 保存文件名
            
        Returns:
            下载的文件路径
        """
        import requests
        
        print(f"📥 下载URL: {url[:60]}...")
        r = requests.get(url, timeout=120, stream=True)
        
        if r.status_code != 200:
            print(f"❌ 下载失败: {r.status_code}")
            return None
        
        # 确定文件名
        if not file_name:
            # 从URL或Content-Disposition获取
            cd = r.headers.get('content-disposition', '')
            if 'filename=' in cd:
                file_name = cd.split('filename=')[1].strip('"\'')
            else:
                ext = Path(url.split('?')[0]).suffix or '.mp4'
                file_name = f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        
        output_path = self.temp_dir / file_name
        with open(output_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        
        file_size = output_path.stat().st_size / 1024 / 1024
        print(f"✅ 下载成功: {output_path.name} ({file_size:.2f} MB)")
        return output_path
    
    # ==================== 音频处理 ====================
    
    def extract_audio(self, media_path: Path, output_format: str = "wav") -> Optional[Path]:
        """
        从视频/音频文件中提取/转换音频为WAV格式
        
        Args:
            media_path: 媒体文件路径
            output_format: 输出格式（默认wav）
            
        Returns:
            音频文件路径
        """
        if not self.deps['ffmpeg']:
            print("❌ 未安装ffmpeg")
            return None
        
        # 检查是否已经是音频文件
        if media_path.suffix.lower() in self.AUDIO_EXTENSIONS:
            if media_path.suffix.lower() == '.wav':
                return media_path
            # 需要转换格式
            output_path = media_path.with_suffix('.wav')
        else:
            output_path = media_path.with_suffix('.wav')
        
        # ffmpeg提取/转换音频（Whisper优化参数）
        cmd = [
            'ffmpeg', '-i', str(media_path),
            '-vn',  # 禁用视频
            '-acodec', 'pcm_s16le',
            '-ar', '16000',  # 16kHz采样率（Whisper推荐）
            '-ac', '1',  # 单声道
            str(output_path),
            '-y',  # 覆盖已存在
            '-loglevel', 'error'  # 减少输出
        ]
        
        print(f"🎵 提取音频: {media_path.name}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                size_mb = output_path.stat().st_size / 1024 / 1024
                print(f"✅ 音频提取成功: {output_path.name} ({size_mb:.2f} MB)")
                return output_path
            else:
                print(f"❌ 音频提取失败: {result.stderr[:300]}")
                return None
        except Exception as e:
            print(f"❌ 音频提取错误: {e}")
            return None
    
    # ==================== 语音转文字 ====================
    
    def transcribe(self, audio_path: Path, model_size: str = "base",
                   language: str = "zh", verbose: bool = False) -> Optional[Dict[str, Any]]:
        """
        使用本地Whisper转录音频
        
        Args:
            audio_path: 音频文件路径
            model_size: 模型大小 (tiny/base/small/medium/large)
            language: 语言代码 (zh/en/auto)
            verbose: 是否显示详细进度
            
        Returns:
            转录结果字典
        """
        if not self.deps['whisper']:
            print("❌ 未安装whisper，请先安装: pip install openai-whisper")
            return None
        
        try:
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
            
        except Exception as e:
            print(f"❌ 转录失败: {e}")
            return None
    
    # ==================== 内容分析 ====================
    
    def analyze_content(self, text: str) -> Dict[str, Any]:
        """
        分析转录文本内容
        
        Args:
            text: 转录文本
            
        Returns:
            分析结果
        """
        # 基础统计
        char_count = len(text)
        word_count = len(text.split())
        
        # 检测语言
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        is_chinese = chinese_chars > char_count * 0.3
        
        # 内容分类关键词
        categories = []
        category_keywords = {
            '会议/访谈': ['会议', '讨论', '汇报', '总结', '采访', '对话'],
            '教学/教程': ['教程', '讲解', '介绍', '如何', '方法', '步骤'],
            '新闻/资讯': ['新闻', '报道', '最新', '热点', '资讯'],
            '播客/对话': ['欢迎收听', '大家好', '我是', '本期', '嘉宾'],
            '职场/求职': ['求职', '面试', '工作', '公司', '职业', '简历'],
            '生活/旅行': ['旅行', '生活', '体验', '房车', '露营', '酒店']
        }
        
        for category, keywords in category_keywords.items():
            if any(kw in text for kw in keywords):
                categories.append(category)
        
        if not categories:
            categories.append('其他')
        
        # 提取关键句子（简单规则：包含数字、时间、总结的句子）
        sentences = re.split(r'[。！？\n]', text)
        key_sentences = [s.strip() for s in sentences if len(s.strip()) > 20][:5]
        
        return {
            'char_count': char_count,
            'word_count': word_count,
            'language': '中文' if is_chinese else '英文',
            'categories': categories,
            'key_sentences': key_sentences,
            'text_preview': text[:1000] + '...' if len(text) > 1000 else text
        }
    
    def generate_summary(self, text: str, max_length: int = 500) -> str:
        """
        生成文本摘要（简单实现）
        
        Args:
            text: 原始文本
            max_length: 摘要最大长度
            
        Returns:
            摘要文本
        """
        # 分段
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        
        if not paragraphs:
            return text[:max_length]
        
        # 取前几个段落，直到达到长度限制
        summary_parts = []
        current_length = 0
        
        for para in paragraphs:
            if current_length + len(para) > max_length:
                break
            summary_parts.append(para)
            current_length += len(para)
        
        return '\n'.join(summary_parts)
    
    # ==================== 完整工作流 ====================
    
    def process_video(self, message_id: str = None, file_key: str = None,
                      file_url: str = None, file_path: Path = None,
                      model_size: str = "base", language: str = "zh") -> Optional[Dict[str, Any]]:
        """
        完整流程：视频 → 音频 → 文字 → 分析
        
        Args:
            message_id: 飞书消息ID（从群聊下载）
            file_key: 飞书文件key
            file_url: 文件URL（直接下载）
            file_path: 本地文件路径
            model_size: Whisper模型大小
            language: 语言
            
        Returns:
            完整处理结果
        """
        print("=" * 60)
        print("🎬 音视频理解技能 - 开始处理")
        print("=" * 60)
        
        media_path = None
        
        # Step 1: 获取文件
        if file_path and Path(file_path).exists():
            media_path = Path(file_path)
            print(f"📁 使用本地文件: {media_path.name}")
        elif message_id and file_key:
            media_path = self.download_from_feishu(message_id, file_key)
        elif file_url:
            media_path = self.download_from_url(file_url)
        
        if not media_path:
            print("❌ 无法获取媒体文件")
            return None
        
        # Step 2: 提取音频
        audio_path = self.extract_audio(media_path)
        if not audio_path:
            return None
        
        # Step 3: 转录音频
        transcript = self.transcribe(audio_path, model_size, language)
        if not transcript:
            return None
        
        # Step 4: 分析内容
        analysis = self.analyze_content(transcript['text'])
        summary = self.generate_summary(transcript['text'])
        
        result = {
            'media_path': str(media_path),
            'audio_path': str(audio_path),
            'transcript': transcript,
            'analysis': analysis,
            'summary': summary,
            'text': transcript['text']
        }
        
        print("\n" + "=" * 60)
        print("✅ 处理完成！")
        print(f"📊 文本长度: {analysis['char_count']} 字符")
        print(f"🏷️ 内容分类: {', '.join(analysis['categories'])}")
        print("=" * 60)
        
        return result
    
    def process_podcast(self, audio_url: str, title: str = None,
                        model_size: str = "base") -> Optional[Dict[str, Any]]:
        """
        播客处理专用接口
        
        Args:
            audio_url: 播客音频URL
            title: 播客标题
            model_size: 模型大小
            
        Returns:
            处理结果
        """
        print(f"🎙️ 处理播客: {title or '未知标题'}")
        return self.process_video(file_url=audio_url, model_size=model_size)
    
    # ==================== 辅助方法 ====================
    
    def _get_feishu_token(self) -> Optional[str]:
        """获取飞书tenant_access_token"""
        import requests
        
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            r = requests.post(url, json={
                "app_id": self.feishu_app_id,
                "app_secret": self.feishu_app_secret
            }, timeout=10)
            return r.json().get("tenant_access_token")
        except Exception as e:
            print(f"❌ 获取Token失败: {e}")
            return None
    
    def save_result(self, result: Dict[str, Any], output_path: Path = None) -> Path:
        """
        保存处理结果到文件
        
        Args:
            result: 处理结果
            output_path: 输出路径（默认temp_dir）
            
        Returns:
            保存的文件路径
        """
        if not output_path:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = self.temp_dir / f"transcript_{timestamp}.json"
        
        # 保存JSON结果
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        # 同时保存纯文本
        text_path = output_path.with_suffix('.txt')
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(f"# 转录文本\n\n")
            f.write(f"文本长度: {result['analysis']['char_count']} 字符\n")
            f.write(f"内容分类: {', '.join(result['analysis']['categories'])}\n")
            f.write(f"\n## 摘要\n\n{result['summary']}\n\n")
            f.write(f"## 完整文本\n\n{result['text']}")
        
        print(f"💾 结果已保存:\n  - JSON: {output_path}\n  - TXT: {text_path}")
        return output_path


# ==================== 便捷函数 ====================

def process_video(message_id: str = None, file_key: str = None, 
                  file_url: str = None, file_path: str = None,
                  model_size: str = "base") -> Optional[Dict[str, Any]]:
    """处理视频的便捷函数"""
    skill = VideoUnderstandingSkill()
    return skill.process_video(
        message_id=message_id,
        file_key=file_key,
        file_url=file_url,
        file_path=Path(file_path) if file_path else None,
        model_size=model_size
    )

def process_podcast(audio_url: str, title: str = None, model_size: str = "base") -> Optional[Dict[str, Any]]:
    """处理播客的便捷函数"""
    skill = VideoUnderstandingSkill()
    return skill.process_podcast(audio_url, title, model_size)

def transcribe_audio(audio_path: str, model_size: str = "base", language: str = "zh") -> Optional[str]:
    """音频转文字的便捷函数"""
    skill = VideoUnderstandingSkill()
    result = skill.transcribe(Path(audio_path), model_size, language)
    return result['text'] if result else None


# ==================== 命令行接口 ====================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='音视频理解技能')
    parser.add_argument('--video', help='本地视频文件路径')
    parser.add_argument('--audio', help='本地音频文件路径')
    parser.add_argument('--url', help='音频/视频URL')
    parser.add_argument('--msg-id', help='飞书消息ID')
    parser.add_argument('--file-key', help='飞书文件key')
    parser.add_argument('--model', default='base', help='Whisper模型 (tiny/base/small/medium/large)')
    parser.add_argument('--lang', default='zh', help='语言代码 (zh/en)')
    parser.add_argument('--save', action='store_true', help='保存结果到文件')
    
    args = parser.parse_args()
    
    skill = VideoUnderstandingSkill()
    
    # 根据输入选择处理方式
    if args.video:
        result = skill.process_video(file_path=Path(args.video), model_size=args.model, language=args.lang)
    elif args.audio:
        result = skill.transcribe(Path(args.audio), args.model, args.lang)
        result = {'text': result} if result else None
    elif args.url:
        result = skill.process_video(file_url=args.url, model_size=args.model, language=args.lang)
    elif args.msg_id and args.file_key:
        result = skill.process_video(message_id=args.msg_id, file_key=args.file_key, 
                                     model_size=args.model, language=args.lang)
    else:
        print("请提供输入: --video, --audio, --url, 或 --msg-id + --file-key")
        sys.exit(1)
    
    if result and args.save:
        skill.save_result(result)
    elif result:
        print("\n" + "=" * 60)
        print("转录结果:")
        print("=" * 60)
        print(result.get('text', result))
