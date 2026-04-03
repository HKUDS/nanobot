"""TTS (Text-to-Speech) module using GPT-SoVITS.

Architecture:
- TTS generation + playback runs in a separate Python environment
- Auto-starts GPT-SoVITS service if not running
- Uses default audio device (no virtual device needed)
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import json
from pathlib import Path
from typing import Optional

from loguru import logger


# ─────────────────────────────────────────────────────────────────────────────
# Content Filter - 决定哪些消息需要TTS
# ─────────────────────────────────────────────────────────────────────────────


def strip_code_and_formulas(text: str) -> str:
    """
    清理文本中的代码块和数学公式。
    
    处理策略：
    1. Markdown代码块（```...```）- 删除整个代码块
    2. 行内代码（`...`）- 删除
    3. LaTeX数学公式（$...$）- 删除
    4. LaTeX显示公式（$$...$$）- 删除
    5. 数学公式（\[...\], \(...\)- 删除
    """
    # Markdown代码块 ```...```
    text = re.sub(r'```[\s\S]*?```', '', text)
    
    # LaTeX显示公式 $$...$$
    text = re.sub(r'\$\$[\s\S]*?\$\$', '', text)
    
    # LaTeX行内公式 $...$
    text = re.sub(r'\$[^$\n]+?\$', '', text)
    
    # 数学公式 \[...\] 和 \(...\)
    text = re.sub(r'\\\[[\s\S]*?\\\]', '', text)
    text = re.sub(r'\\\([\s\S]*?\\\)', '', text)
    
    # 行内代码 `...`
    text = re.sub(r'`[^`]+`', '', text)
    
    return text


def split_into_sentences(text: str) -> list[str]:
    """
    将文本智能分句（基于标点符号）。
    
    支持：
    - 中文标点：。！？；
    - 英文标点：. ? ! ;
    - 英文引号："（英文句子结束）
    
    返回句子列表，每句至少2个字符。
    """
    if not text or not text.strip():
        return []
    
    # 替换英文引号为占位符
    placeholder_map = {}
    counter = 0
    
    def replace_quote(match):
        nonlocal counter
        key = f"__Q{counter}__"
        placeholder_map[key] = match.group(0)
        counter += 1
        return key
    
    text = re.sub(r'"[^"]*"', replace_quote, text)
    
    # 分句标点
    sentence_delimiters = r'[。！？；\.!?;"]\s*'
    parts = re.split(sentence_delimiters, text)
    
    sentences = []
    for part in parts:
        part = part.strip()
        # 恢复占位符
        for key, value in placeholder_map.items():
            part = part.replace(key, value)
        if len(part) >= 2:
            sentences.append(part)
    
    return sentences


def chunk_by_sentence(text: str) -> list[str]:
    """将文本按句子分块"""
    sentences = split_into_sentences(text)
    if not sentences:
        return [text] if text.strip() else []
    return sentences


def should_speak(text: str) -> bool:
    """
    智能判断文本是否应该触发TTS朗读。
    
    策略：
    1. 先清理代码块和数学公式
    2. 清理后必须有中文
    3. 英文比例不能过高（70%，支持中英双语）
    4. 有足够的中文字符（≥3个）
    """
    if not text or not text.strip():
        return False
    
    cleaned = strip_code_and_formulas(text)
    
    if not cleaned or not cleaned.strip():
        return False
    
    # 必须有中文
    if not re.search(r'[\u4e00-\u9fff]', cleaned):
        return False
    
    # 英文比例检查
    english_chars = len(re.findall(r'[a-zA-Z]', cleaned))
    total_chars = len(re.sub(r'\s', '', cleaned))
    if total_chars > 0 and english_chars / total_chars > 0.7:
        return False
    
    # 中文字符检查
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', cleaned))
    if chinese_chars < 3:
        return False
    
    return True


def extract_interactive_opener(text: str) -> str:
    """
    从长消息中提取需要朗读的部分。

    策略：
    1. 先移除 Runtime Context 前缀
    2. 如果有分隔符（---）：
       - 检查正文部分是否"任务型"结构
       - 任务型 → 截取分隔符之前
       - 纯聊天 → 返回全文
    3. 如果没有分隔符：
       - 文本 < 300字 → 全部返回
       - 文本 ≥ 300字 → 截取前240字
    """
    # 移除 Runtime Context 前缀
    runtime_context_pattern = r'^\[Runtime Context[^\]]*\]\s*'
    text = re.sub(runtime_context_pattern, '', text, count=1).strip()

    # 分隔符检测
    separators = ['---', '***', '―――', '——', '___']
    first_sep_pos = len(text)
    matched_sep = None
    for sep in separators:
        pos = text.find(sep)
        if pos != -1 and pos < first_sep_pos:
            first_sep_pos = pos
            matched_sep = sep

    if matched_sep and first_sep_pos < len(text):
        before_sep = text[:first_sep_pos].strip()
        after_sep = text[first_sep_pos + len(matched_sep):].strip()

        is_task_content = bool(
            re.search(r'#{1,3}\s', after_sep) or
            re.search(r'^\d+[.)、]', after_sep, re.MULTILINE) or
            re.search(r'^[A-Z][A-Za-z\s]+:$', after_sep, re.MULTILINE)
        )

        if not is_task_content:
            return text

        return before_sep

    if len(text) > 300:
        return text[:240].strip()

    return text


def clean_text_for_speech(text: str) -> str:
    """
    清理文本，只保留朗读内容。

    清理策略：
    1. 移除自定义格式emoji（如(ᗜ ˰ ᗜ)）
    2. 移除Unicode emoji符号
    3. 移除分隔符
    4. 移除文件路径
    5. 移除URL链接
    6. 移除Markdown格式
    7. 移除HTML标签
    8. 清理多余空白
    """
    # 1. 去除自定义格式的emoji表情
    text = re.sub(r'\([^)\u0000-\u007F]*\)', '', text)
    
    # 2. 去除Unicode emoji符号
    text = re.sub(r'[\U0001F300-\U0001F9FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF😀-🙏]', '', text)
    
    # 3. 去除分隔符
    for sep in ['---', '***', '―――', '——', '___']:
        text = text.replace(sep, '')
    
    # 4. 去除路径
    text = re.sub(r'[A-Za-z]:\\[\w\\\-. ]+(?:\.(?:py|js|json|yaml|yml|txt|docx|pdf|xlsx|png|jpg|gif|mp3|wav))?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'/[\w/\-. ]+(?:\.(?:py|js|json|yaml|yml|txt|docx|pdf|xlsx|png|jpg|gif|mp3|wav))?', '', text, flags=re.IGNORECASE)
    
    # 5. 去除URL链接
    text = re.sub(r'https?://\S+', '', text)
    
    # 6. 去除Markdown格式符号
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
    text = re.sub(r'`{1,3}([^`]+)`{1,3}', r'\1', text)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'^[\-\*\•·]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+[.)、]\s+', '', text, flags=re.MULTILINE)
    
    # 7. 去除HTML标签
    text = re.sub(r'<[^>]+>', '', text)
    
    # 8. 清理多余空白
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def strip_trailing_emoji(text: str) -> str:
    """清理文本末尾的emoji"""
    text = re.sub(r'\([^)\u0000-\u007F]*\)\s*$', '', text)
    text = re.sub(r'[\U0001F300-\U0001F9FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF😀-🙏]\s*$', '', text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# TTS Worker Script - 在独立环境中运行
# ─────────────────────────────────────────────────────────────────────────────

TTS_WORKER_SCRIPT = '''
import requests
import sounddevice as sd
import soundfile as sf
import sys
import os
import time
import json

def check_gpt_sovits_running(port=9880):
    try:
        requests.get(f"http://127.0.0.1:{port}/", timeout=2)
        return True
    except:
        return False

def start_gpt_sovits_service(gpt_path, gpt_weight, sovits_weight, port=9880):
    import subprocess
    
    try:
        result = subprocess.run(
            f'netstat -ano | findstr :{port}',
            shell=True, capture_output=True, text=True
        )
        for line in result.stdout.strip().split('\\n'):
            if 'LISTENING' in line:
                pid = line.split()[-1]
                if pid:
                    subprocess.run(f'taskkill /F /PID {pid}', shell=True, capture_output=True)
    except:
        pass
    
    os.chdir(gpt_path)
    subprocess.Popen([
        sys.executable, "api.py",
        "-g", gpt_weight,
        "-s", sovits_weight
    ])

def generate_and_play(api_url, refer_wav, prompt_text, text, prompt_lang="zh", text_lang="zh"):
    params = {
        "refer_wav_path": refer_wav,
        "prompt_text": prompt_text,
        "prompt_language": prompt_lang,
        "text": text,
        "text_language": text_lang,
    }
    
    r = requests.get(api_url, params=params, timeout=60)
    r.raise_for_status()
    
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False, mode='wb') as f:
        f.write(r.content)
        audio_path = f.name
    
    try:
        data, sr = sf.read(audio_path, dtype="float32")
        if data is not None and len(data) >= sr * 0.1:
            sd.play(data, sr)
            sd.wait()
    finally:
        os.unlink(audio_path)

def main():
    config = json.loads(sys.stdin.read())
    
    api_url = config["api_url"]
    refer_wav = config["refer_wav"]
    prompt_text = config["prompt_text"]
    prompt_lang = config.get("prompt_language", "zh")
    text_lang = config.get("text_language", "zh")
    text = config["text"]
    gpt_path = config.get("gpt_path", "")
    gpt_weight = config.get("gpt_weight", "")
    sovits_weight = config.get("sovits_weight", "")
    auto_start = config.get("auto_start", True)
    wait_startup = config.get("wait_startup", 5)
    
    if not check_gpt_sovits_running():
        if auto_start and gpt_path and gpt_weight and sovits_weight:
            print(f"Starting GPT-SoVITS service...", file=sys.stderr)
            start_gpt_sovits_service(gpt_path, gpt_weight, sovits_weight)
            print(f"Waiting {wait_startup}s for service to start...", file=sys.stderr)
            time.sleep(wait_startup)
        else:
            print("Error: GPT-SoVITS service not running and auto_start is disabled", file=sys.stderr)
            sys.exit(1)
    
    generate_and_play(api_url, refer_wav, prompt_text, text, prompt_lang, text_lang)
    print("OK")

if __name__ == "__main__":
    main()
'''


# ─────────────────────────────────────────────────────────────────────────────
# TTS Manager
# ─────────────────────────────────────────────────────────────────────────────

class TTSManager:
    """
    TTS 管理器
    
    功能：
    1. 检查/启动 GPT-SoVITS 服务
    2. 生成并播放 TTS 音频
    3. 在独立环境中运行所有操作
    """
    
    def __init__(
        self,
        python_path: str = "python",
        api_url: str = "http://127.0.0.1:9880/",
        refer_wav: str = "reference.wav",
        prompt_text: str = "",
        prompt_language: str = "zh",
        text_language: str = "zh",
        gpt_path: str = "",
        gpt_weight: str = "",
        sovits_weight: str = "",
        auto_start: bool = True,
        wait_startup: int = 8,
    ):
        self.python_path = python_path
        self.api_url = api_url
        self.refer_wav = refer_wav
        self.prompt_text = prompt_text
        self.prompt_language = prompt_language
        self.text_language = text_language
        self.gpt_path = gpt_path
        self.gpt_weight = gpt_weight
        self.sovits_weight = sovits_weight
        self.auto_start = auto_start
        self.wait_startup = wait_startup
        
        self._python_available = Path(python_path).exists() if python_path != "python" else True
        
        logger.info(
            "[TTS] TTSManager initialized: api={}, tts_env={}",
            api_url, python_path
        )
    
    def check_service(self) -> bool:
        """检查 GPT-SoVITS 服务是否运行"""
        try:
            import requests
            requests.get(self.api_url, timeout=2)
            return True
        except:
            return False
    
    def ensure_service_running(self) -> bool:
        """确保 GPT-SoVITS 服务运行"""
        if self.check_service():
            return True
        
        if not self.auto_start:
            return False
        
        if not all([self.gpt_path, self.gpt_weight, self.sovits_weight]):
            return False
        
        logger.info("[TTS] Auto-starting GPT-SoVITS service...")
        self._start_service()
        return True
    
    def _start_service(self):
        """启动 GPT-SoVITS 服务"""
        import subprocess
        
        port = 9880
        try:
            result = subprocess.run(
                f'netstat -ano | findstr :{port}',
                shell=True, capture_output=True, text=True
            )
            killed = []
            for line in result.stdout.strip().split('\n'):
                if 'LISTENING' in line:
                    pid = line.split()[-1]
                    if pid and pid not in killed:
                        subprocess.run(f'taskkill /F /PID {pid}', shell=True, capture_output=True)
                        killed.append(pid)
        except:
            pass
        
        subprocess.Popen([
            self.python_path, "api.py",
            "-g", self.gpt_weight,
            "-s", self.sovits_weight
        ], cwd=self.gpt_path)
        
        time.sleep(self.wait_startup)
    
    def generate_and_play(self, text: str, wait: bool = True) -> bool:
        """生成音频并播放"""
        if not self._python_available:
            logger.warning("[TTS] Python environment not available")
            return False
        
        if not self.check_service():
            if not self.ensure_service_running():
                return False
        
        try:
            config = {
                "api_url": self.api_url,
                "refer_wav": self.refer_wav,
                "prompt_text": self.prompt_text,
                "prompt_language": self.prompt_language,
                "text_language": self.text_language,
                "text": text,
                "gpt_path": self.gpt_path,
                "gpt_weight": self.gpt_weight,
                "sovits_weight": self.sovits_weight,
                "auto_start": False,
                "wait_startup": 0,
            }
            
            logger.debug("[TTS] Speaking: {}", text[:50])
            
            if wait:
                result = subprocess.run(
                    [self.python_path, "-c", TTS_WORKER_SCRIPT],
                    input=json.dumps(config),
                    capture_output=True,
                    timeout=60,
                    encoding='utf-8',
                    errors='replace'
                )
                if result.returncode != 0:
                    logger.warning("[TTS] TTS error: {}", result.stderr[:200])
                    return False
                logger.info("[TTS] Spoken: {} chars", len(text))
                return True
            else:
                thread = threading.Thread(
                    target=self._play_async,
                    args=(config,),
                    daemon=True
                )
                thread.start()
                return True
                
        except subprocess.TimeoutExpired:
            logger.warning("[TTS] TTS timeout")
            return False
        except Exception as e:
            logger.warning("[TTS] TTS error: {}", e)
            return False
    
    def _play_async(self, config: dict):
        """异步播放"""
        try:
            result = subprocess.run(
                [self.python_path, "-c", TTS_WORKER_SCRIPT],
                input=json.dumps(config),
                capture_output=True,
                timeout=60,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode != 0:
                logger.warning("[TTS] Async TTS failed: {}", result.stderr[:200])
            else:
                logger.info("[TTS] Async TTS completed")
        except Exception as e:
            logger.warning("[TTS] Async TTS error: {}", e)
    
    def speak(self, text: str) -> bool:
        """快捷方法：检查并朗读"""
        if not should_speak(text):
            return False
        cleaned = clean_text_for_speech(text)
        if not cleaned:
            return False
        return self.generate_and_play(cleaned, wait=False)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton instance
# ─────────────────────────────────────────────────────────────────────────────

_tts_instance: Optional[TTSManager] = None


def get_tts() -> Optional[TTSManager]:
    """获取 TTS 实例"""
    return _tts_instance


def init_tts(
    python_path: str = "python",
    api_url: str = "http://127.0.0.1:9880/",
    refer_wav: str = "reference.wav",
    prompt_text: str = "",
    prompt_language: str = "zh",
    text_language: str = "zh",
    gpt_path: str = "",
    gpt_weight: str = "",
    sovits_weight: str = "",
    auto_start: bool = True,
    wait_startup: int = 8,
    **kwargs
) -> TTSManager:
    """初始化 TTS 实例"""
    global _tts_instance
    _tts_instance = TTSManager(
        python_path=python_path,
        api_url=api_url,
        refer_wav=refer_wav,
        prompt_text=prompt_text,
        prompt_language=prompt_language,
        text_language=text_language,
        gpt_path=gpt_path,
        gpt_weight=gpt_weight,
        sovits_weight=sovits_weight,
        auto_start=auto_start,
        wait_startup=wait_startup,
    )
    return _tts_instance


def speak(text: str) -> bool:
    """快捷函数"""
    if _tts_instance:
        return _tts_instance.speak(text)
    return False
