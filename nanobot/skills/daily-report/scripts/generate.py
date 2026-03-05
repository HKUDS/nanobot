#!/usr/bin/env python3
"""
HiperOne早晚报生成器 - V5 格式
"""

import json
from datetime import datetime
from typing import Dict, List, Optional

# V5 格式模板
V5_TEMPLATE = """# 🦞 HiperOneAI{report_type}（{date_str}）
## 今日核心要闻（8条精选）
{headlines}
## 📝 深度文章 | {deep_title}
{deep_content}
## 📊 关键信号
{signals}
## 📎 附录：详细数据支撑
### A1. 资本支出详情
{appendix_a1}
### A2. 股价变动详情
{appendix_a2}
### A3. {theme}对比表
{appendix_a3}
### A4. 产品发布追踪
{appendix_a4}
### A5. AI竞争形态对比
{appendix_a5}
### A6. 原始素材库（10条精选）
{appendix_a6}
### A7. 待追踪事项
{appendix_a7}
📄 完整版：{feishu_url}
💡 推荐理由：{recommendation}
✅ 来源说明：今日从{source_count}个信源获取{news_count}条新闻"""

# 关键信号模板
SIGNAL_TEMPLATE = """• 💰 资本：{capital}
• 🥊 竞争：{competition}
• 📉 市场：{market}
• 🚀 技术：{technology}
• 🏢 企业：{enterprise}
• 🇨🇳 中国：{china}
• 🌍 海外：{overseas}
• ⚠️ 风险：{risk}"""

def generate_daily_report(
    report_type: str,  # "早报" 或 "晚报"
    date: str,
    news_data: List[Dict],
    deep_topic: str = "",
    feishu_url: str = "",
    output_dir: str = "~/.nanobot/workspace"
) -> Dict:
    """
    生成 V5 格式早晚报
    
    Args:
        report_type: "早报" 或 "晚报"
        date: 日期字符串，如 "2026-02-08"
        news_data: 新闻数据列表
        deep_topic: 深度文章主题
        feishu_url: 飞书文档链接
        output_dir: 输出目录
    
    Returns:
        {"md_file": str, "content": str}
    """
    
    # 格式化日期
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    date_str = f"{date_obj.year}年{date_obj.month}月{date_obj.day}日"
    
    # 1. 生成8条核心要闻
    headlines = "\n".join([
        f"{i+1}. {news['emoji']} {news['title']} ({news['source']}, {news['date']})"
        for i, news in enumerate(news_data[:8])
    ])
    
    # 2. 深度文章（纯文本，无章节标题）
    deep_title = deep_topic or "AI行业深度观察"
    deep_content = generate_deep_article(news_data, deep_topic)
    
    # 3. 关键信号
    signals = generate_signals(news_data)
    
    # 4. 附录
    appendix = generate_appendix(news_data)
    
    # 5. 推荐理由
    recommendation = generate_recommendation(news_data)
    
    # 填充模板
    content = V5_TEMPLATE.format(
        report_type=report_type,
        date_str=date_str,
        headlines=headlines,
        deep_title=deep_title,
        deep_content=deep_content,
        signals=signals,
        appendix_a1=appendix['a1'],
        appendix_a2=appendix['a2'],
        appendix_a3=appendix['a3'],
        appendix_a4=appendix['a4'],
        appendix_a5=appendix['a5'],
        appendix_a6=appendix['a6'],
        appendix_a7=appendix['a7'],
        theme=appendix['theme'],
        feishu_url=feishu_url or "https://feishu.cn/docx/...",
        recommendation=recommendation,
        source_count=len(set(n['source'] for n in news_data)),
        news_count=len(news_data)
    )
    
    # 保存文件
    filename = f"HiperOneAI{report_type}_{date}_V5.md"
    filepath = f"{output_dir}/{filename}"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return {
        "md_file": filepath,
        "content": content,
        "filename": filename
    }

def generate_deep_article(news_data: List[Dict], topic: str) -> str:
    """生成深度文章（纯文本，无章节标题）"""
    
    # 找出最核心的一条新闻作为深度分析基础
    main_news = news_data[0] if news_data else {"title": "AI行业观察", "content": ""}
    
    # 构建纯文本深度分析
    article = f"""{main_news.get('content', main_news.get('summary', ''))}

这让人不禁好奇：当{topic or 'AI'}开始亲手塑造自己的未来，我们是否已经准备好了应对这个加速循环的刹车？也许真正的挑战不在于技术本身，而在于如何在效率与安全之间找到那个微妙的平衡点。"""
    
    return article.strip()

def generate_signals(news_data: List[Dict]) -> str:
    """生成关键信号"""
    
    # 从新闻中提取各类信号
    signals = {
        'capital': '暂无重大资本动态',
        'competition': '暂无重大竞争动态',
        'market': '市场平稳',
        'technology': '技术稳步发展',
        'enterprise': '企业正常运营',
        'china': '国内AI生态活跃',
        'overseas': '海外AI动态频繁',
        'risk': '暂无重大风险'
    }
    
    # 根据新闻内容填充信号
    for news in news_data:
        title = news.get('title', '').lower()
        if '融资' in title or 'investment' in title or 'funding' in title:
            signals['capital'] = news['title'][:50]
        if '竞争' in title or '广告' in title or 'super bowl' in title:
            signals['competition'] = news['title'][:50]
        if '股价' in title or 'stock' in title or 'market' in title:
            signals['market'] = news['title'][:50]
        if '发布' in title or '模型' in title or 'gpt' in title or 'claude' in title:
            signals['technology'] = news['title'][:50]
    
    return SIGNAL_TEMPLATE.format(**signals)

def generate_appendix(news_data: List[Dict]) -> Dict:
    """生成附录 A1-A7"""
    
    # A1. 资本支出
    a1 = "| 公司 | 投入/融资 | 金额 | 时间 |\n|------|----------|------|------|"
    
    # A2. 股价变动
    a2 = "| 公司 | 涨幅 | 时间段 | 原因 |\n|------|------|--------|------|"
    
    # A3. 主题对比
    a3 = "| 维度 | 方案A | 方案B |\n|------|-------|-------|"
    theme = "AI竞争"
    
    # A4. 产品发布
    a4 = "| 产品 | 公司 | 发布时间 | 核心能力 |\n|------|------|----------|----------|"
    
    # A5. 竞争形态
    a5 = "| 维度 | OpenAI | Anthropic |\n|------|--------|-----------|"
    
    # A6. 原始素材
    a6_items = []
    for i, news in enumerate(news_data[:10], 1):
        a6_items.append(f"{i}. {news['title']} - {news['source']} - {news.get('url', '')}")
    a6 = "\n".join(a6_items)
    
    # A7. 待追踪
    a7 = "- [ ] 待补充具体追踪事项"
    
    return {
        'a1': a1,
        'a2': a2,
        'a3': a3,
        'theme': theme,
        'a4': a4,
        'a5': a5,
        'a6': a6,
        'a7': a7
    }

def generate_recommendation(news_data: List[Dict]) -> str:
    """生成推荐理由"""
    if not news_data:
        return "今日AI行业动态值得关注"
    
    # 找出最有价值的新闻作为推荐理由
    main_news = news_data[0]
    return f"{main_news['title'][:40]}...标志着AI行业重要进展"

if __name__ == "__main__":
    # 测试示例
    test_news = [
        {
            "emoji": "🚀",
            "title": "OpenAI发布GPT-5.3-Codex",
            "source": "OpenAI官方博客",
            "date": "2/5",
            "content": "OpenAI于2月5日正式发布GPT-5.3-Codex，这是Codex产品的一次重大战略转型。"
        },
        {
            "emoji": "🎭",
            "title": "Anthropic发布Claude Opus 4.6",
            "source": "Anthropic官方",
            "date": "2/5",
            "content": "Anthropic推出Claude Opus 4.6，在代理编码领域成为行业领先模型。"
        }
    ]
    
    result = generate_daily_report(
        report_type="早报",
        date="2026-02-08",
        news_data=test_news,
        deep_topic="自举AI"
    )
    
    print(f"Generated: {result['md_file']}")
