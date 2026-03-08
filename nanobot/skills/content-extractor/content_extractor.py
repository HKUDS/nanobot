#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Content Extractor - 统一内容提取中心
支持多平台内容抓取：小宇宙、抖音、微信公众号、B站等
"""

import os
import re
import json
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass
from enum import Enum

class Platform(Enum):
    """支持的平台"""
    XIAOYUZHOU = "xiaoyuzhou"  # 小宇宙播客
    DOUYIN = "douyin"          # 抖音
    WECHAT = "wechat"          # 微信公众号
    BILIBILI = "bilibili"      # B站
    XIAOHONGSHU = "xiaohongshu"  # 小红书
    UNKNOWN = "unknown"

class ExtractError(Exception):
    """提取异常"""
    pass

@dataclass
class ExtractResult:
    """提取结果"""
    platform: Platform
    title: str
    content: str
    author: Optional[str] = None
    publish_time: Optional[str] = None
    media_urls: List[str] = None  # 音频/视频URL
    images: List[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.media_urls is None:
            self.media_urls = []
        if self.images is None:
            self.images = []
        if self.metadata is None:
            self.metadata = {}

class ContentExtractor:
    """统一内容提取器"""
    
    def __init__(self):
        self.extractors = {
            Platform.XIAOYUZHOU: self._extract_xiaoyuzhou,
            Platform.DOUYIN: self._extract_douyin,
            Platform.WECHAT: self._extract_wechat,
            Platform.BILIBILI: self._extract_bilibili,
            Platform.XIAOHONGSHU: self._extract_xiaohongshu,
        }
    
    def detect_platform(self, url: str) -> Platform:
        """检测URL所属平台"""
        domain = urlparse(url).netloc.lower()
        
        if 'xiaoyuzhoufm.com' in domain:
            return Platform.XIAOYUZHOU
        elif 'douyin.com' in domain or 'iesdouyin.com' in domain:
            return Platform.DOUYIN
        elif 'mp.weixin.qq.com' in domain:
            return Platform.WECHAT
        elif 'bilibili.com' in domain or 'b23.tv' in domain:
            return Platform.BILIBILI
        elif 'xiaohongshu.com' in domain or 'xhslink.com' in domain:
            return Platform.XIAOHONGSHU
        
        return Platform.UNKNOWN
    
    def extract(self, url: str, **options) -> ExtractResult:
        """
        提取内容
        
        Args:
            url: 内容链接
            **options:
                - download_media: 是否下载音视频 (默认False)
                - save_path: 保存路径
                - extract_text: 是否提取文字内容 (默认True)
        
        Returns:
            ExtractResult 提取结果
        """
        platform = self.detect_platform(url)
        
        if platform == Platform.UNKNOWN:
            raise ExtractError(f"不支持的平台: {url}")
        
        if platform not in self.extractors:
            raise ExtractError(f"暂不支持提取该平台: {platform.value}")
        
        try:
            return self.extractors[platform](url, **options)
        except Exception as e:
            raise ExtractError(f"提取失败 [{platform.value}]: {str(e)}")
    
    def batch_extract(self, urls: List[str], **options) -> List[ExtractResult]:
        """批量提取"""
        results = []
        for url in urls:
            try:
                result = self.extract(url, **options)
                results.append(result)
            except ExtractError as e:
                print(f"❌ 提取失败: {url} - {e}")
        return results
    
    # ========== 小宇宙播客 ==========
    
    def _extract_xiaoyuzhou(self, url: str, **options) -> ExtractResult:
        """提取小宇宙播客 - 优化版"""
        
        # 方案1: 快速模式 - 直接用curl提取音频URL
        if options.get('fast_mode', True):
            return self._extract_xiaoyuzhou_fast(url, **options)
        
        # 方案2: 完整模式 - 用Playwright渲染页面获取完整信息
        return self._extract_xiaoyuzhou_full(url, **options)
    
    def _extract_xiaoyuzhou_fast(self, url: str, **options) -> ExtractResult:
        """快速提取小宇宙播客（curl方式）"""
        import subprocess
        import re
        
        print("🚀 使用快速模式提取...")
        
        try:
            # 1. 获取网页内容
            cmd = ['curl', '-sL', url, '-H', 'User-Agent: Mozilla/5.0']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            html = result.stdout
            
            # 2. 提取标题
            title = "未知标题"
            title_match = re.search(r'<title>(.*?)</title>', html)
            if title_match:
                title = title_match.group(1).strip()
                # 清理标题中的后缀
                title = re.sub(r'\s*-\s*小宇宙.*$', '', title)
            
            # 3. 提取音频URL（多种格式尝试）
            audio_urls = []
            
            # 尝试1: 直接从页面中提取audio标签
            audio_pattern = r'(https?://[^"\'\s]+\.(?:m4a|mp3|aac))[^"\'\s]*'
            matches = re.findall(audio_pattern, html)
            audio_urls.extend(matches)
            
            # 尝试2: 从JSON数据中提取
            json_pattern = r'"audio_url"[:\s]*"([^"]+)"'
            json_matches = re.findall(json_pattern, html)
            audio_urls.extend([m.replace('\\/', '/') for m in json_matches])
            
            # 去重
            audio_urls = list(set(audio_urls))
            
            # 4. 提取描述（从meta标签）
            description = ""
            desc_match = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', html)
            if desc_match:
                description = desc_match.group(1)
            
            # 5. 提取节目信息
            podcast_name = ""
            ep_match = re.search(r'"podcast_name"[:\s]*"([^"]+)"', html)
            if ep_match:
                podcast_name = ep_match.group(1)
            
            result = ExtractResult(
                platform=Platform.XIAOYUZHOU,
                title=title,
                content=description,
                author=podcast_name,
                media_urls=audio_urls,
                metadata={
                    "url": url,
                    "extract_mode": "fast",
                    "audio_count": len(audio_urls)
                }
            )
            
            # 6. 快速下载音频（如果启用）
            if options.get('download_media') and audio_urls and options.get('save_path'):
                print(f"⬇️  下载音频中...")
                try:
                    saved_path = self._download_file_fast(
                        audio_urls[0], 
                        options['save_path'], 
                        f"{title}.m4a"
                    )
                    result.metadata['downloaded_audio'] = saved_path
                    print(f"✅ 已下载: {saved_path}")
                except Exception as e:
                    print(f"⚠️ 下载失败: {e}")
            
            return result
            
        except subprocess.TimeoutExpired:
            print("⏱️ 快速模式超时，切换到完整模式...")
            return self._extract_xiaoyuzhou_full(url, **options)
        except Exception as e:
            print(f"⚠️ 快速模式失败: {e}")
            return self._extract_xiaoyuzhou_full(url, **options)
    
    def _download_file_fast(self, url: str, save_dir: str, filename: str, timeout: int = 300) -> str:
        """快速下载文件（带进度显示）"""
        import subprocess
        import os
        
        os.makedirs(save_dir, exist_ok=True)
        
        # 清理文件名
        filename = re.sub(r'[\\/*?:"<>|]', "_", filename)
        filepath = os.path.join(save_dir, filename)
        
        print(f"   下载: {url[:60]}...")
        print(f"   保存到: {filepath}")
        
        # 使用curl下载，带进度显示
        cmd = [
            'curl', '-L', url, 
            '-o', filepath,
            '-H', 'User-Agent: Mozilla/5.0',
            '--max-time', str(timeout),
            '--progress-bar'
        ]
        
        try:
            subprocess.run(cmd, check=True, timeout=timeout)
            
            # 检查文件大小
            file_size = os.path.getsize(filepath)
            print(f"   文件大小: {file_size / 1024 / 1024:.1f} MB")
            
            return filepath
        except subprocess.CalledProcessError as e:
            raise ExtractError(f"下载失败: {e}")
        except subprocess.TimeoutExpired:
            raise ExtractError(f"下载超时 (> {timeout}秒)")
    
    def _extract_xiaoyuzhou_full(self, url: str, **options) -> ExtractResult:
        """提取小宇宙播客"""
        try:
            # 小宇宙网页版解析
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until='networkidle')
                
                # 提取信息
                title = page.locator('h1').first.inner_text() if page.locator('h1').count() > 0 else "未知标题"
                
                # 尝试提取音频URL
                audio_url = None
                try:
                    # 查找audio标签
                    audio_elements = page.locator('audio').all()
                    if audio_elements:
                        audio_url = audio_elements[0].get_attribute('src')
                    else:
                        # 从页面脚本中提取
                        page_content = page.content()
                        audio_match = re.search(r'"audio_url":"([^"]+)"', page_content)
                        if audio_match:
                            audio_url = audio_match.group(1).replace('\\/', '/')
                except:
                    pass
                
                # 提取描述
                description = ""
                try:
                    desc_elem = page.locator('.description, .episode-description, [class*="desc"]').first
                    if desc_elem:
                        description = desc_elem.inner_text()
                except:
                    pass
                
                browser.close()
                
                result = ExtractResult(
                    platform=Platform.XIAOYUZHOU,
                    title=title,
                    content=description,
                    media_urls=[audio_url] if audio_url else [],
                    metadata={"url": url}
                )
                
                # 下载音频
                if options.get('download_media') and audio_url and options.get('save_path'):
                    saved_path = self._download_file(audio_url, options['save_path'], f"{title}.mp3")
                    result.metadata['downloaded_audio'] = saved_path
                
                return result
                
        except ImportError:
            raise ExtractError("playwright未安装。请运行: pip install playwright")
        except Exception as e:
            raise ExtractError(f"小宇宙提取失败: {str(e)}")
    
    # ========== 抖音 ==========
    
    def _extract_douyin(self, url: str, **options) -> ExtractResult:
        """提取抖音视频"""
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # 处理短链接
                if 'v.douyin.com' in url or 'b23.tv' in url:
                    page.goto(url, wait_until='networkidle')
                    url = page.url
                
                page.goto(url, wait_until='networkidle')
                
                # 提取标题
                title = ""
                try:
                    title = page.locator('.title, [data-e2e="video-desc"], .video-title').first.inner_text()
                except:
                    title = "抖音视频"
                
                # 提取视频URL
                video_url = None
                try:
                    # 查找video标签
                    video_elem = page.locator('video').first
                    if video_elem:
                        video_url = video_elem.get_attribute('src')
                    
                    # 如果失败，尝试从网络请求获取
                    if not video_url:
                        # 监听网络请求（需要更复杂的实现）
                        pass
                        
                except:
                    pass
                
                # 提取作者
                author = ""
                try:
                    author = page.locator('.author, [data-e2e="user-name"], .nickname').first.inner_text()
                except:
                    pass
                
                browser.close()
                
                result = ExtractResult(
                    platform=Platform.DOUYIN,
                    title=title,
                    content="",
                    author=author,
                    media_urls=[video_url] if video_url else [],
                    metadata={"url": url}
                )
                
                # 下载视频
                if options.get('download_media') and video_url and options.get('save_path'):
                    saved_path = self._download_file(video_url, options['save_path'], f"{title}.mp4")
                    result.metadata['downloaded_video'] = saved_path
                
                return result
                
        except ImportError:
            raise ExtractError("playwright未安装。请运行: pip install playwright")
        except Exception as e:
            raise ExtractError(f"抖音提取失败: {str(e)}")
    
    # ========== 微信公众号 ==========
    
    def _extract_wechat(self, url: str, **options) -> ExtractResult:
        """提取微信公众号文章"""
        try:
            # 复用现有的wechat-article-fetcher
            import sys
            sys.path.insert(0, '/Users/delta/.nanobot/workspace/skills/wechat-article-fetcher')
            from wechat_fetcher import WechatArticleFetcher
            
            fetcher = WechatArticleFetcher()
            article = fetcher.fetch(url)
            
            return ExtractResult(
                platform=Platform.WECHAT,
                title=article.get('title', ''),
                content=article.get('content', ''),
                author=article.get('author', ''),
                publish_time=article.get('publish_time', ''),
                images=article.get('images', []),
                metadata={"url": url, "source": "wechat-article-fetcher"}
            )
            
        except ImportError:
            raise ExtractError("wechat-article-fetcher未找到")
        except Exception as e:
            raise ExtractError(f"微信公众号提取失败: {str(e)}")
    
    # ========== B站 ==========
    
    def _extract_bilibili(self, url: str, **options) -> ExtractResult:
        """提取B站视频"""
        try:
            from playwright.sync_api import sync_playwright
            import re
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until='networkidle')
                
                # 提取标题
                title = ""
                try:
                    title = page.locator('h1').first.inner_text()
                except:
                    pass
                
                # 提取视频信息
                # B站视频需要通过API获取下载链接
                bvid_match = re.search(r'(BV[0-9A-Za-z]{10})', url)
                if bvid_match:
                    bvid = bvid_match.group(1)
                    # 调用B站API获取视频信息
                    api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
                    try:
                        response = requests.get(api_url, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        })
                        data = response.json()
                        if data.get('data'):
                            video_data = data['data']
                            title = video_data.get('title', title)
                            author = video_data.get('owner', {}).get('name', '')
                            desc = video_data.get('desc', '')
                    except:
                        author = ""
                        desc = ""
                else:
                    author = ""
                    desc = ""
                
                browser.close()
                
                return ExtractResult(
                    platform=Platform.BILIBILI,
                    title=title,
                    content=desc,
                    author=author,
                    media_urls=[],  # B站需要额外处理下载
                    metadata={"url": url, "bvid": bvid if 'bvid' in locals() else None}
                )
                
        except ImportError:
            raise ExtractError("playwright未安装。请运行: pip install playwright")
        except Exception as e:
            raise ExtractError(f"B站提取失败: {str(e)}")
    
    # ========== 小红书 ==========
    
    def _extract_xiaohongshu(self, url: str, **options) -> ExtractResult:
        """提取小红书笔记"""
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until='networkidle')
                
                # 提取标题
                title = ""
                try:
                    title = page.locator('.title, .note-title, h1').first.inner_text()
                except:
                    pass
                
                # 提取内容
                content = ""
                try:
                    content = page.locator('.content, .note-content, .desc').first.inner_text()
                except:
                    pass
                
                # 提取图片
                images = []
                try:
                    img_elements = page.locator('.img, .image, img').all()
                    for img in img_elements:
                        src = img.get_attribute('src')
                        if src:
                            images.append(src)
                except:
                    pass
                
                browser.close()
                
                return ExtractResult(
                    platform=Platform.XIAOHONGSHU,
                    title=title,
                    content=content,
                    images=images,
                    metadata={"url": url}
                )
                
        except ImportError:
            raise ExtractError("playwright未安装。请运行: pip install playwright")
        except Exception as e:
            raise ExtractError(f"小红书提取失败: {str(e)}")
    
    # ========== 工具方法 ==========
    
    def _download_file(self, url: str, save_dir: str, filename: str) -> str:
        """下载文件"""
        os.makedirs(save_dir, exist_ok=True)
        
        # 清理文件名
        filename = re.sub(r'[\\/*?:"<>|]', "_", filename)
        filepath = os.path.join(save_dir, filename)
        
        response = requests.get(url, stream=True, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return filepath

# 便捷函数
def extract(url: str, **options) -> ExtractResult:
    """
    提取内容
    
    Args:
        url: 内容链接
        **options:
            - fast_mode: 是否使用快速模式 (默认True)
            - download_media: 是否下载音视频 (默认False)
            - save_path: 保存路径
    """
    extractor = ContentExtractor()
    return extractor.extract(url, **options)

def extract_fast(url: str, download: bool = False, save_path: str = "./downloads") -> ExtractResult:
    """快速提取（仅获取音频URL，不下载）"""
    return extract(url, fast_mode=True, download_media=download, save_path=save_path)

def extract_full(url: str, **options) -> ExtractResult:
    """完整提取（使用Playwright获取完整信息）"""
    return extract(url, fast_mode=False, **options)

def batch_extract(urls: List[str], **options) -> List[ExtractResult]:
    """批量提取"""
    extractor = ContentExtractor()
    return extractor.batch_extract(urls, **options)

def detect_platform(url: str) -> Platform:
    """检测平台"""
    extractor = ContentExtractor()
    return extractor.detect_platform(url)

if __name__ == "__main__":
    # 测试
    print("Content Extractor 测试")
    extractor = ContentExtractor()
    
    test_urls = [
        "https://www.xiaoyuzhoufm.com/episode/xxx",
        "https://mp.weixin.qq.com/s/xxx",
    ]
    
    for url in test_urls:
        platform = extractor.detect_platform(url)
        print(f"{url} -> {platform.value}")
