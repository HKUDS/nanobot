#!/usr/bin/env python3
"""
Long-form article generator
Transforms data/outline into comprehensive content
"""

import json
import argparse
from datetime import datetime
from typing import List, Dict

class LongFormWriter:
    def __init__(self, article_type: str, target_words: int):
        self.article_type = article_type
        self.target_words = target_words
        self.chapters = []
        
    def create_structure(self, topic: str, key_points: List[str]) -> Dict:
        """L1: Create article blueprint"""
        words_per_chapter = self.target_words // len(key_points)
        
        blueprint = {
            "topic": topic,
            "type": self.article_type,
            "target_words": self.target_words,
            "chapters": []
        }
        
        for i, point in enumerate(key_points, 1):
            blueprint["chapters"].append({
                "order": i,
                "title": point,
                "target_words": words_per_chapter,
                "subsections": []
            })
        
        return blueprint
    
    def expand_chapter(self, chapter: Dict, data_source: Dict) -> str:
        """L2: Expand single chapter with depth"""
        content_parts = []
        
        # Chapter header
        content_parts.append(f"## {chapter['title']}\n")
        
        # Core content (expanded based on type)
        if self.article_type == "report":
            content_parts.append(self._expand_report_chapter(chapter, data_source))
        elif self.article_type == "tutorial":
            content_parts.append(self._expand_tutorial_chapter(chapter, data_source))
        elif self.article_type == "analysis":
            content_parts.append(self._expand_analysis_chapter(chapter, data_source))
        
        return "\n".join(content_parts)
    
    def _expand_report_chapter(self, chapter: Dict, data: Dict) -> str:
        """Expand as report section"""
        sections = []
        
        # Overview
        sections.append(f"### 概述\n\n本章深入分析 {chapter['title']} 的关键要素...\n")
        
        # Key findings
        sections.append("### 核心发现\n")
        
        # Data points from source
        if "findings" in data:
            for finding in data["findings"][:3]:
                sections.append(f"- **{finding['title']}**：{finding['description']}\n")
        
        # Detailed analysis
        sections.append("\n### 详细分析\n\n")
        sections.append("基于收集的数据，我们发现以下关键趋势：\n\n")
        
        # Add depth markers
        sections.append("[EXPAND: 添加具体案例和数据支撑]\n")
        
        return "\n".join(sections)
    
    def _expand_tutorial_chapter(self, chapter: Dict, data: Dict) -> str:
        """Expand as tutorial section"""
        sections = []
        
        # Concept
        sections.append(f"### 概念理解\n\n{chapter['title']} 是...\n")
        
        # Step by step
        sections.append("### 操作步骤\n\n")
        sections.append("1. **准备工作**\n   - 检查环境\n   - 安装依赖\n\n")
        sections.append("2. **具体实施**\n   - 执行命令\n   - 验证结果\n\n")
        sections.append("3. **常见问题**\n   - 错误处理\n   - 优化建议\n\n")
        
        # Example
        sections.append("### 实战案例\n\n")
        sections.append("```bash\n# 示例代码\ncommand example\n```\n\n")
        
        return "\n".join(sections)
    
    def _expand_analysis_chapter(self, chapter: Dict, data: Dict) -> str:
        """Expand as analysis section"""
        sections = []
        
        # Background
        sections.append(f"### 背景\n\n{chapter['title']} 的重要性在于...\n")
        
        # Analysis
        sections.append("### 深度分析\n\n")
        sections.append("从多个维度观察，我们发现：\n\n")
        
        # Multiple perspectives
        sections.append("**视角一：技术层面**\n")
        sections.append("技术实现的关键在于...\n\n")
        
        sections.append("**视角二：用户体验**\n")
        sections.append("从用户反馈来看...\n\n")
        
        sections.append("**视角三：市场趋势**\n")
        sections.append("结合行业数据...\n\n")
        
        return "\n".join(sections)
    
    def enrich_cases(self, content: str, chat_data: List[Dict]) -> str:
        """L3: Add real cases from chat history"""
        enriched = content
        
        # Find case insertion points
        if "[CASE:" in content:
            for case_marker in range(1, 10):
                marker = f"[CASE:{case_marker}]"
                if marker in enriched and chat_data:
                    case = chat_data.pop(0) if chat_data else None
                    if case:
                        case_text = f"\n> **真实案例**：{case.get('text', '')[:150]}...\n> \n> —— 来自群友反馈\n"
                        enriched = enriched.replace(marker, case_text)
        
        return enriched
    
    def polish_content(self, content: str) -> str:
        """L4: Apply writing style rules"""
        # Remove AI filler phrases
        fillers = [
            "值得注意的是",
            "需要指出的是", 
            "不可否认的是",
            "首先...其次...最后",
            "让我们来看看",
            "这意味着"
        ]
        
        polished = content
        for filler in fillers:
            polished = polished.replace(filler, "")
        
        # Add variation markers
        if "1." in polished and "2." in polished and "3." in polished:
            polished += "\n\n<!-- Note: Convert 3-part to 2 or 4 for variation -->\n"
        
        return polished
    
    def generate(self, topic: str, data_source: Dict, chat_cases: List[Dict] = None) -> str:
        """Main generation workflow"""
        print(f"📝 Generating {self.article_type}: {topic}")
        print(f"   Target: {self.target_words} words\n")
        
        # L1: Structure
        print("L1: Creating blueprint...")
        key_points = data_source.get("key_points", [])
        blueprint = self.create_structure(topic, key_points)
        print(f"   {len(key_points)} chapters planned\n")
        
        # L2: Expand chapters
        print("L2: Expanding chapters...")
        full_chapters = []
        for chapter in blueprint["chapters"]:
            print(f"   Writing: {chapter['title']}")
            chapter_content = self.expand_chapter(chapter, data_source)
            full_chapters.append(chapter_content)
        print()
        
        # L3: Enrich
        print("L3: Adding cases and data...")
        if chat_cases:
            for i, chapter in enumerate(full_chapters):
                full_chapters[i] = self.enrich_cases(chapter, chat_cases[:3])
                chat_cases = chat_cases[3:]
        print()
        
        # L4: Polish
        print("L4: Polishing content...")
        for i, chapter in enumerate(full_chapters):
            full_chapters[i] = self.polish_content(chapter)
        print()
        
        # Assemble final document
        header = f"""# {topic}

**类型**：{self.article_type}  
**目标字数**：{self.target_words}  
**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}  

---

"""
        
        body = "\n\n---\n\n".join(full_chapters)
        
        conclusion = f"""

---

## 总结

本文深入探讨了 {topic} 的核心要素，从多个维度分析了关键发现。

**核心要点回顾**：
{chr(10).join([f"- {p}" for p in key_points[:5]])}

**下一步行动建议**：
- 根据实际需求选择合适方案
- 持续关注社区最新动态
- 实践验证并反馈问题

---

*本文由 Long Form Writer 生成 | 基于真实数据分析*
"""
        
        return header + body + conclusion


def main():
    parser = argparse.ArgumentParser(description='Generate long-form content')
    parser.add_argument('--topic', required=True, help='Article topic')
    parser.add_argument('--type', default='report', choices=['report', 'tutorial', 'analysis'])
    parser.add_argument('--words', type=int, default=5000, help='Target word count')
    parser.add_argument('--data', required=True, help='JSON data source file')
    parser.add_argument('--cases', help='Chat cases JSON file (optional)')
    parser.add_argument('--output', default='output.md', help='Output file')
    
    args = parser.parse_args()
    
    # Load data
    with open(args.data, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Load cases if provided
    cases = None
    if args.cases:
        with open(args.cases, 'r', encoding='utf-8') as f:
            cases = json.load(f)
    
    # Generate
    writer = LongFormWriter(args.type, args.words)
    content = writer.generate(args.topic, data, cases)
    
    # Save
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(content)
    
    # Stats
    word_count = len(content.split())
    print(f"✅ Generated: {args.output}")
    print(f"   Words: {word_count}")
    print(f"   Chapters: {len(data.get('key_points', []))}")


if __name__ == "__main__":
    main()