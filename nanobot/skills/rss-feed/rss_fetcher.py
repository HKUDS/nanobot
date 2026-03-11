#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS自动拉取脚本 - HiperOne晨间内容工厂
每小时检查一次RSS源，输出结构化数据
"""

import feedparser
import json
import time
import socket
from datetime import datetime, timedelta
from pathlib import Path

# 设置全局socket超时
socket.setdefaulttimeout(30)  # 30秒超时

# RSS源配置
RSS_SOURCES = {
    "google_news_ai": {
        "name": "Google News AI",
        "url": "https://news.google.com/rss/search?q=artificial+intelligence&hl=en-US&gl=US&ceid=US:en",
        "category": "综合AI新闻"
    },
    "techcrunch_ai": {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "category": "AI创业/融资"
    },
    "wired_ai": {
        "name": "Wired AI",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
        "category": "深度分析"
    },
    "ars_technica": {
        "name": "Ars Technica",
        "url": "https://arstechnica.com/tag/artificial-intelligence/feed/",
        "category": "技术视角"
    },
    "机器之心": {
        "name": "机器之心",
        "url": "https://www.jiqizhixin.com/rss",
        "category": "国内AI媒体"
    },
    "虎嗅": {
        "name": "虎嗅",
        "url": "https://www.huxiu.com/rss",
        "category": "商业视角",
        "backup_url": "https://rsshub.app/huxiu/article"  # 备用源
    },
    "量子位": {
        "name": "量子位",
        "url": "https://www.qbitai.com/feed",
        "category": "国内AI媒体"
    },
    "雷锋网": {
        "name": "雷锋网",
        "url": "https://www.leiphone.com/feed",
        "category": "科技媒体"
    }
}

# 数据存储路径
DATA_DIR = Path("~/.hiperone/workspace/01-Projects/daily-report/01-raw-materials/rss-data")
DATA_DIR.mkdir(exist_ok=True)

class RSSFetcher:
    def __init__(self):
        self.data_dir = DATA_DIR
        self.news_cache = []
        
    def fetch_rss_with_retry(self, source_key, source_config, max_retries=3, request_timeout=30):
        """带重试的RSS拉取"""
        urls_to_try = [source_config['url']]
        
        # 如果有备用URL，加入尝试列表
        if 'backup_url' in source_config:
            urls_to_try.append(source_config['backup_url'])
        
        # 设置当前操作的socket超时
        original_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(request_timeout)
        
        try:
            for url in urls_to_try:
                for attempt in range(max_retries):
                    try:
                        print(f"📡 正在拉取: {source_config['name']} (尝试{attempt+1}/{max_retries})...")
                        
                        feed = feedparser.parse(url)
                        
                        if feed.bozo and len(feed.entries) == 0:
                            print(f"⚠️ {source_config['name']} 解析警告: {feed.bozo_exception}")
                            if attempt < max_retries - 1:
                                time.sleep(2 ** attempt)  # 指数退避
                                continue
                            else:
                                # 所有重试都失败，返回空
                                return []
                        
                        articles = []
                        for entry in feed.entries[:20]:  # 取最新20条
                            article = {
                                "title": entry.get('title', ''),
                                "link": entry.get('link', ''),
                                "published": entry.get('published', ''),
                                "summary": entry.get('summary', '')[:500],
                                "source": source_config['name'],
                                "category": source_config['category'],
                                "fetched_at": datetime.now().isoformat()
                            }
                            articles.append(article)
                        
                        if articles:
                            print(f"✅ {source_config['name']}: 获取 {len(articles)} 条")
                            return articles
                        elif attempt < max_retries - 1:
                            time.sleep(2 ** attempt)
                            continue
                        else:
                            return []
                        
                    except socket.timeout:
                        print(f"⏱️ {source_config['name']} 超时 (尝试{attempt+1}/{max_retries})")
                        if attempt < max_retries - 1:
                            time.sleep(2 ** attempt)
                        continue
                        
                    except Exception as e:
                        print(f"❌ {source_config['name']} 拉取失败 (尝试{attempt+1}): {e}")
                        if attempt < max_retries - 1:
                            time.sleep(2 ** attempt)
                        continue
            
            print(f"❌ {source_config['name']}: 所有尝试均失败")
            return []
        finally:
            # 恢复原始超时设置
            socket.setdefaulttimeout(original_timeout)
    
    def fetch_rss(self, source_key, source_config):
        """拉取单个RSS源（兼容旧接口）"""
        return self.fetch_rss_with_retry(source_key, source_config)
    
    def fetch_all(self, hours_back=24, max_total_time=300):
        """拉取所有RSS源，带总超时控制"""
        all_articles = []
        start_time = time.time()
        
        print(f"\n🚀 开始RSS拉取 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        for key, config in RSS_SOURCES.items():
            # 检查总超时
            if time.time() - start_time > max_total_time:
                print(f"⏱️ 总时间超过{max_total_time}秒，停止拉取")
                break
            
            try:
                articles = self.fetch_rss(key, config)
                all_articles.extend(articles)
            except Exception as e:
                print(f"❌ {config['name']} 异常: {e}")
            
            time.sleep(1)  # 避免请求过快
        
        print("=" * 60)
        print(f"📊 总计获取: {len(all_articles)} 条新闻\n")
        
        return all_articles
    
    def filter_recent(self, articles, hours=24):
        """过滤最近24小时的新闻"""
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = []
        
        for article in articles:
            try:
                # 解析发布时间
                pub_date = self.parse_date(article.get('published', ''))
                if pub_date and pub_date > cutoff:
                    recent.append(article)
            except:
                # 无法解析日期的，默认保留
                recent.append(article)
        
        return recent
    
    def parse_date(self, date_str):
        """解析各种日期格式"""
        formats = [
            '%a, %d %b %Y %H:%M:%S %z',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%d %H:%M:%S',
            '%a, %d %b %Y %H:%M:%S GMT',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except:
                continue
        
        return None
    
    def save_to_json(self, articles, filename=None):
        """保存到JSON文件"""
        if filename is None:
            filename = f"rss_data_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        
        filepath = self.data_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        
        print(f"💾 数据已保存: {filepath}")
        return filepath
    
    def deduplicate(self, articles):
        """去重（基于标题相似度）"""
        seen_titles = set()
        unique = []
        
        for article in articles:
            title = article['title'].lower().strip()
            # 简单去重：完全相同标题
            if title not in seen_titles:
                seen_titles.add(title)
                unique.append(article)
        
        return unique
    
    def run(self):
        """完整执行流程"""
        # 1. 拉取所有RSS
        articles = self.fetch_all()
        
        # 2. 去重
        articles = self.deduplicate(articles)
        print(f"🔄 去重后: {len(articles)} 条")
        
        # 3. 过滤最近24小时
        recent = self.filter_recent(articles, hours=24)
        print(f"⏰ 24小时内: {len(recent)} 条")
        
        # 4. 保存数据
        if recent:
            filepath = self.save_to_json(recent)
            
            # 同时保存一份latest供早报生成使用
            latest_path = self.data_dir / "latest_rss_data.json"
            self.save_to_json(recent, "latest_rss_data.json")
            
            return recent, filepath
        else:
            print("⚠️ 没有获取到24小时内的新闻")
            return [], None

def main():
    """主函数"""
    fetcher = RSSFetcher()
    articles, filepath = fetcher.run()
    
    # 输出统计
    if articles:
        sources = {}
        for a in articles:
            src = a['source']
            sources[src] = sources.get(src, 0) + 1
        
        print("\n📈 各源统计:")
        for src, count in sorted(sources.items(), key=lambda x: -x[1]):
            print(f"  • {src}: {count}条")
    
    return articles

if __name__ == "__main__":
    articles = main()
    print(f"\n✅ RSS拉取完成，共 {len(articles)} 条新闻")
