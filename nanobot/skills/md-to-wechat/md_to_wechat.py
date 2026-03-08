#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown to WeChat HTML Converter
将Markdown转换为微信公众号兼容的HTML
"""

import re
import sys
from pathlib import Path
from datetime import datetime

class MarkdownToWechatConverter:
    """Markdown转微信公众号HTML转换器"""
    
    # 默认主题色配置
    DEFAULT_COLORS = {
        'primary': '#d4a574',      # 金色 - 主色调
        'accent': '#e07a5f',       # 珊瑚色 - 强调色
        'dark': '#2d3436',         # 深色 - 表格头部
        'text': '#1a1a1a',         # 主文字
        'text_secondary': '#666',  # 次要文字
        'bg_light': '#f5f5f5',     # 浅灰背景
        'bg_card': '#f8f9fa',      # 卡片背景
    }
    
    def __init__(self, colors=None, title=None, subtitle=None, author=None, tags=None):
        """初始化转换器"""
        self.colors = colors or self.DEFAULT_COLORS
        self.title = title or ""
        self.subtitle = subtitle or ""
        self.author = author or "非凡产研"
        self.tags = tags or []
        self.word_count = 0
        
    def convert(self, markdown_text):
        """将Markdown文本转换为微信公众号HTML"""
        # 统计字数
        self.word_count = len(re.findall(r'[\u4e00-\u9fa5]', markdown_text)) + len(re.findall(r'[a-zA-Z]+', markdown_text))
        
        # 转换各个元素（按优先级顺序）
        html = self._convert_code_blocks(markdown_text)
        html = self._convert_headers(html)
        html = self._convert_blockquotes(html)
        html = self._convert_tables(html)
        html = self._convert_inline_code(html)
        html = self._convert_bold(html)
        html = self._convert_italic(html)
        html = self._convert_lists(html)
        html = self._convert_scene_blocks(html)
        html = self._convert_conclusion_blocks(html)
        html = self._convert_links(html)
        html = self._convert_paragraphs(html)
        
        # 包装为完整HTML文档
        return self._wrap_html(html)
    
    def _convert_headers(self, text):
        """转换标题为带装饰线的章节标题"""
        # H1 标题 - 文章主标题（在wrap_html中处理，这里移除）
        text = re.sub(r'^#\s+.+$', '', text, flags=re.MULTILINE)
        
        # H2 标题 - 章节标题
        def h2_replacer(match):
            content = match.group(1).strip()
            return f'''<div style="margin:48px 0 24px;">
    <div style="display:flex;align-items:center;gap:12px;">
        <div style="width:6px;height:28px;background:{self.colors['primary']};border-radius:3px;"></div>
        <h2 style="font-family:'Songti SC','SimSun',serif;font-size:24px;font-weight:700;color:{self.colors['text']};margin:0;">{content}</h2>
    </div>
</div>'''
        
        # H3 标题 - 小节标题
        def h3_replacer(match):
            content = match.group(1).strip()
            return f'''<h3 style="font-size:18px;font-weight:600;margin:32px 0 14px;color:#333;padding-left:12px;border-left:3px solid #e0e0e0;">{content}</h3>'''
        
        text = re.sub(r'^##\s+(.+)$', h2_replacer, text, flags=re.MULTILINE)
        text = re.sub(r'^###\s+(.+)$', h3_replacer, text, flags=re.MULTILINE)
        return text
    
    def _convert_blockquotes(self, text):
        """转换引用块为带引号的样式"""
        lines = text.split('\n')
        result = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # 检查是否是引用块开始
            if line.strip().startswith('>'):
                quote_lines = []
                author = ""
                
                # 收集所有连续的行
                while i < len(lines) and lines[i].strip().startswith('>'):
                    quote_line = lines[i].strip()[1:].strip()
                    
                    # 检查是否是作者行
                    if quote_line.startswith('—') or quote_line.startswith('-'):
                        author = quote_line[1:].strip()
                    elif quote_line:
                        quote_lines.append(quote_line)
                    
                    i += 1
                
                # 构建引用块HTML
                if quote_lines:
                    content = ' '.join(quote_lines)
                    content = re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:#000;">\1</strong>', content)
                    
                    author_html = f'<div style="font-size:13px;color:{self.colors["text_secondary"]};text-align:right;">—— {author}</div>' if author else ''
                    
                    quote_html = f'''<div style="background:{self.colors['bg_light']};border-radius:12px;padding:24px;margin:24px 0;box-shadow:0 2px 12px rgba(0,0,0,0.04);">
    <div style="font-size:48px;color:{self.colors['primary']};opacity:0.3;line-height:1;margin-bottom:-10px;">"</div>
    <p style="font-family:'Songti SC','SimSun',serif;font-size:15px;color:{self.colors['text']};margin:0 0 12px;line-height:1.8;">
        {content}
    </p>
    {author_html}
</div>'''
                    result.append(quote_html)
            else:
                result.append(line)
                i += 1
        
        return '\n'.join(result)
    
    def _convert_tables(self, text):
        """转换表格为内联样式表格"""
        lines = text.split('\n')
        result = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # 检查是否是表格开始
            if '|' in line and not line.strip().startswith('<'):
                # 收集所有表格行
                table_lines = []
                while i < len(lines) and '|' in lines[i]:
                    table_lines.append(lines[i])
                    i += 1
                
                # 过滤分隔线行
                content_lines = [l for l in table_lines if not re.match(r'^\|[-:|\s]+\|$', l.strip())]
                
                if len(content_lines) >= 1:
                    # 解析表头
                    headers = [c.strip() for c in content_lines[0].split('|')[1:-1] if c.strip()]
                    
                    # 解析数据行
                    rows = []
                    for line in content_lines[1:]:
                        cells = [c.strip() for c in line.split('|')[1:-1] if c.strip()]
                        if cells:
                            rows.append(cells)
                    
                    # 构建HTML表格
                    header_html = ''.join([f'<th style="padding:14px 12px;text-align:left;font-weight:600;font-size:13px;">{h}</th>' for h in headers])
                    
                    rows_html = ''
                    for i_row, row in enumerate(rows):
                        bg_style = 'background:#fafafa;' if i_row % 2 == 1 else ''
                        cells_html = ''.join([f'<td style="padding:14px 12px;color:#333;{bg_style}">{c}</td>' for c in row])
                        border_style = 'border-bottom:1px solid #eee;' if i_row < len(rows) - 1 else ''
                        rows_html += f'<tr style="{border_style}{bg_style}">{cells_html}</tr>'
                    
                    table_html = f'''<table style="width:100%;border-collapse:collapse;margin:20px 0;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,0.06);font-size:14px;">
    <thead>
        <tr style="background:{self.colors['dark']};color:#fff;">
            {header_html}
        </tr>
    </thead>
    <tbody>
        {rows_html}
    </tbody>
</table>'''
                    result.append(table_html)
            else:
                result.append(line)
                i += 1
        
        return '\n'.join(result)
    
    def _convert_code_blocks(self, text):
        """转换代码块为深色背景样式"""
        pattern = r'```(\w+)?\n(.*?)```'
        
        def code_replacer(match):
            code = match.group(2).strip()
            # 转义HTML特殊字符
            code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # 替换换行
            code = code.replace('\n', '<br>\n')
            code = code.replace('  ', '&nbsp;&nbsp;')
            
            return f'''<div style="background:#1e1e1e;color:#d4d4d4;padding:20px;border-radius:12px;overflow-x:auto;margin:24px 0;font-family:'Menlo','Monaco','Courier New',monospace;font-size:13px;line-height:1.6;box-shadow:0 4px 20px rgba(0,0,0,0.15);">
{code}
</div>'''
        
        return re.sub(pattern, code_replacer, text, flags=re.DOTALL)
    
    def _convert_inline_code(self, text):
        """转换行内代码"""
        return re.sub(r'`([^`]+)`', r'<code style="background:#f0f0f0;padding:2px 6px;border-radius:4px;font-family:monospace;font-size:0.9em;color:#e07a5f;">\1</code>', text)
    
    def _convert_bold(self, text):
        """转换加粗文本"""
        return re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:#000;">\1</strong>', text)
    
    def _convert_italic(self, text):
        """转换斜体文本"""
        return re.sub(r'\*(.+?)\*', r'<em style="font-style:italic;color:#666;">\1</em>', text)
    
    def _convert_lists(self, text):
        """转换列表"""
        lines = text.split('\n')
        result = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # 检查是否是无序列表
            if re.match(r'^[-\*]\s+', line.strip()) and not line.strip().startswith('<'):
                items = []
                while i < len(lines) and re.match(r'^[-\*]\s+', lines[i].strip()):
                    item = re.sub(r'^[-\*]\s+', '', lines[i].strip())
                    items.append(item)
                    i += 1
                
                items_html = ''.join([f'<li style="margin-bottom:6px;color:#555;">{item}</li>' for item in items])
                ul_html = f'<ul style="margin:0 0 16px;padding-left:20px;color:#555;">{items_html}</ul>'
                result.append(ul_html)
            else:
                result.append(line)
                i += 1
        
        return '\n'.join(result)
    
    def _convert_paragraphs(self, text):
        """转换段落"""
        lines = text.split('\n')
        result = []
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            # 如果已经是HTML标签，直接保留
            if line.startswith('<') and not line.startswith('<strong') and not line.startswith('<em') and not line.startswith('<code'):
                result.append(lines[i])
                i += 1
                continue
            
            # 空行跳过
            if not line:
                result.append('')
                i += 1
                continue
            
            # 普通段落
            if line:
                result.append(f'<p style="font-size:15px;line-height:1.8;color:#333;margin:0 0 16px;text-align:justify;">{line}</p>')
            
            i += 1
        
        return '\n'.join(result)
    
    def _convert_links(self, text):
        """转换链接"""
        return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" style="color:#e07a5f;text-decoration:none;">\1</a>', text)
    
    def _convert_scene_blocks(self, text):
        """转换场景块（特殊标记）"""
        pattern = r'^【(.+?)】\n(.+?)(?=\n\n|\Z)'
        
        def scene_replacer(match):
            label = match.group(1)
            content = match.group(2).strip()
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:#000;">\1</strong>', content)
            # 处理高亮数字
            content = re.sub(r'<span style="color:#e07a5f;font-weight:700;font-size:1\.1em;">(.+?)</span>', 
                           f'<span style="color:{self.colors["accent"]};font-weight:700;font-size:1.1em;background:linear-gradient(120deg,transparent 0%,rgba(212,165,116,0.2) 100%);padding:2px 8px;border-radius:4px;">\\1</span>', 
                           content)
            
            return f'''<div style="background:linear-gradient(135deg,#f8f9fa 0%,#e9ecef 100%);border-left:4px solid {self.colors['accent']};padding:24px;margin:28px 0;border-radius:0 12px 12px 0;box-shadow:0 4px 20px rgba(0,0,0,0.06);">
    <div style="display:inline-block;background:{self.colors['accent']};color:white;font-size:11px;font-weight:600;padding:4px 12px;border-radius:20px;margin-bottom:12px;letter-spacing:1px;">{label}</div>
    <p style="font-family:'Songti SC','SimSun',serif;font-size:16px;color:{self.colors['text']};margin:0;line-height:1.8;">
        {content}
    </p>
</div>'''
        
        return re.sub(pattern, scene_replacer, text, flags=re.MULTILINE | re.DOTALL)
    
    def _convert_conclusion_blocks(self, text):
        """转换结论块（特殊标记）"""
        pattern = r'^【结论】\n(.+?)(?=\n\n|\Z)'
        
        def conclusion_replacer(match):
            content = match.group(1).strip()
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong style="color:#fff;">\1</strong>', content)
            
            return f'''<div style="background:linear-gradient(135deg,{self.colors['dark']} 0%,#1a1a1a 100%);color:#fff;padding:24px;margin:32px 0;border-radius:12px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,0.15);">
    <div style="display:inline-block;background:{self.colors['primary']};color:#1a1a1a;font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px;margin-bottom:12px;letter-spacing:1px;">结论</div>
    <p style="color:#fff;font-size:18px;font-weight:700;margin:0;line-height:1.6;">
        {content}
    </p>
</div>'''
        
        return re.sub(pattern, conclusion_replacer, text, flags=re.MULTILINE | re.DOTALL)
    
    def _wrap_html(self, content):
        """包装为完整HTML文档"""
        tags_html = ''.join([f'<span style="display:inline-block;background:#f5f5f5;padding:6px 16px;margin:0 6px 8px;font-size:12px;color:#666;border-radius:20px;">{tag}</span>' for tag in self.tags])
        
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self.title}</title>
</head>
<body style="margin:0;padding:0;background-color:#f7f8fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei','Helvetica Neue',Arial,sans-serif;">

<!-- 文章容器 -->
<div style="max-width:680px;margin:0 auto;background:#ffffff;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

    <!-- 头部区域 -->
    <div style="background:linear-gradient(135deg,#fafafa 0%,#f0f0f0 100%);padding:50px 24px 40px;text-align:center;border-bottom:2px solid #000000;">
        <div style="font-size:12px;letter-spacing:3px;color:{self.colors['primary']};margin-bottom:20px;font-weight:600;">COVER STORY</div>
        <h1 style="font-size:32px;line-height:1.3;margin:0 0 20px;font-weight:900;color:#1a1a1a;font-family:'Songti SC','SimSun',serif;letter-spacing:-0.02em;">
            {self.title}
        </h1>
        <div style="width:40px;height:3px;background:{self.colors['primary']};margin:24px auto;"></div>
        <p style="font-size:17px;color:#666;margin:0;line-height:1.6;font-style:italic;">
            {self.subtitle}
        </p>
    </div>

    <!-- 正文内容 -->
    <div style="padding:0 24px 40px;">
        {content}
        
        <!-- 页脚 -->
        <div style="margin-top:48px;padding-top:32px;border-top:1px solid #eee;text-align:center;">
            <div style="margin-bottom:16px;">
                <span style="display:inline-block;background:#f5f5f5;padding:6px 16px;margin:0 6px 8px;font-size:12px;color:#666;border-radius:20px;">字数：约{self.word_count}字</span>
                <span style="display:inline-block;background:#f5f5f5;padding:6px 16px;margin:0 6px 8px;font-size:12px;color:#666;border-radius:20px;">{self.author}</span>
                {tags_html}
            </div>
            <p style="font-size:12px;color:#999;line-height:1.6;margin:0;">
                生成时间：{datetime.now().strftime('%Y-%m-%d')}
            </p>
        </div>
    </div>
</div>

</body>
</html>'''


def convert_file(input_path, output_path=None, title=None, subtitle=None, author=None, tags=None):
    """转换Markdown文件为HTML文件"""
    input_file = Path(input_path)
    if not input_file.exists():
        print(f"❌ 文件不存在: {input_path}")
        return None
    
    if output_path is None:
        output_path = input_file.with_suffix('.html')
    
    # 读取Markdown内容
    with open(input_file, 'r', encoding='utf-8') as f:
        markdown_text = f.read()
    
    # 从Markdown中提取标题（如果未指定）
    if title is None:
        title_match = re.search(r'^#\s+(.+)$', markdown_text, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
        else:
            title = input_file.stem
    
    # 创建转换器并转换
    converter = MarkdownToWechatConverter(title=title, subtitle=subtitle, author=author, tags=tags)
    html = converter.convert(markdown_text)
    
    # 保存HTML文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✅ 转换完成: {output_path}")
    print(f"📊 字数统计: {converter.word_count} 字")
    return output_path


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='将Markdown转换为微信公众号兼容的HTML')
    parser.add_argument('input', help='输入的Markdown文件路径')
    parser.add_argument('-o', '--output', help='输出的HTML文件路径')
    parser.add_argument('-t', '--title', help='文章标题')
    parser.add_argument('-s', '--subtitle', help='副标题')
    parser.add_argument('-a', '--author', default='非凡产研', help='作者')
    parser.add_argument('--tags', help='标签（逗号分隔）')
    
    args = parser.parse_args()
    
    tags = args.tags.split(',') if args.tags else []
    convert_file(args.input, args.output, args.title, args.subtitle, args.author, tags)
