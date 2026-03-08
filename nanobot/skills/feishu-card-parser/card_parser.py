#!/usr/bin/env python3
"""
飞书卡片消息解析器
解析飞书 Interactive Card 为可读文本
"""

import json
import re
from typing import List, Dict, Any, Union


def parse_card_message(card_content: Union[str, Dict]) -> Dict[str, Any]:
    """
    解析飞书卡片消息
    
    Args:
        card_content: 卡片 JSON 字符串或字典
        
    Returns:
        解析结果字典
    """
    # 解析 JSON
    if isinstance(card_content, str):
        try:
            card = json.loads(card_content)
        except json.JSONDecodeError:
            return {
                "title": "",
                "text_content": card_content,
                "markdown_content": card_content,
                "images": [],
                "links": [],
                "mentions": [],
                "error": "Invalid JSON"
            }
    else:
        card = card_content
    
    result = {
        "title": "",
        "text_content": "",
        "markdown_content": "",
        "images": [],
        "links": [],
        "mentions": [],
        "code_blocks": []
    }
    
    # 提取标题
    if "title" in card:
        result["title"] = card["title"]
    
    # 解析 content 数组
    content_blocks = card.get("content", [])
    
    text_parts = []
    md_parts = []
    
    for block_group in content_blocks:
        for element in block_group:
            tag = element.get("tag", "")
            
            if tag == "text":
                text = element.get("text", "")
                style = element.get("style", [])
                text_parts.append(text)
                md_parts.append(apply_markdown_style(text, style))
                
            elif tag == "lark_md":
                text = element.get("content", "")
                text_parts.append(text)
                md_parts.append(text)
                
            elif tag == "img":
                image_key = element.get("image_key", "")
                if image_key:
                    result["images"].append(image_key)
                    md_parts.append(f"\n![图片]({image_key})\n")
                    
            elif tag == "link":
                url = element.get("url", "")
                text = element.get("text", url)
                if url:
                    result["links"].append(url)
                    md_parts.append(f"[{text}]({url})")
                    
            elif tag == "at":
                user_id = element.get("user_id", "")
                user_name = element.get("user_name", user_id)
                if user_id:
                    result["mentions"].append({"id": user_id, "name": user_name})
                    md_parts.append(f"[@{user_name}]({user_id})")
                    
            elif tag == "code_block":
                language = element.get("language", "")
                text = element.get("text", "")
                result["code_blocks"].append({"language": language, "code": text})
                md_parts.append(f"\n```{language}\n{text}\n```\n")
                
            elif tag == "url":
                # 链接预览卡片
                url = element.get("url", "")
                title = element.get("title", "")
                if url:
                    result["links"].append(url)
                    md_parts.append(f"\n[{title or url}]({url})\n")
    
    result["text_content"] = "".join(text_parts).strip()
    result["markdown_content"] = "".join(md_parts).strip()
    
    return result


def apply_markdown_style(text: str, styles: List[str]) -> str:
    """应用 Markdown 样式"""
    result = text
    if "bold" in styles:
        result = f"**{result}**"
    if "italic" in styles:
        result = f"*{result}*"
    if "strike" in styles or "strikethrough" in styles:
        result = f"~~{result}~~"
    if "code" in styles:
        result = f"`{result}`"
    if "underline" in styles:
        result = f"<u>{result}</u>"
    return result


def card_to_markdown(card_content: Union[str, Dict]) -> str:
    """
    将卡片转换为 Markdown 格式
    
    Args:
        card_content: 卡片内容
        
    Returns:
        Markdown 字符串
    """
    result = parse_card_message(card_content)
    
    lines = []
    
    # 标题
    if result["title"]:
        lines.append(f"# {result['title']}\n")
    
    # 正文
    if result["markdown_content"]:
        lines.append(result["markdown_content"])
    
    # 图片
    if result["images"]:
        lines.append("\n---\n**图片:**")
        for img in result["images"]:
            lines.append(f"- `{img}`")
    
    # 链接
    if result["links"]:
        lines.append("\n**链接:**")
        for link in result["links"]:
            lines.append(f"- {link}")
    
    # @用户
    if result["mentions"]:
        lines.append("\n**提到:**")
        for mention in result["mentions"]:
            lines.append(f"- @{mention['name']} ({mention['id']})")
    
    return "\n".join(lines)


def extract_urls_from_text(text: str) -> List[str]:
    """从文本中提取 URL"""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    return re.findall(url_pattern, text)


# 命令行接口
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="飞书卡片消息解析器")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径")
    parser.add_argument("--text", "-t", help="直接输入 JSON 字符串")
    parser.add_argument("--format", "-f", choices=["json", "markdown", "text"], 
                        default="markdown", help="输出格式")
    
    args = parser.parse_args()
    
    # 获取输入
    if args.input:
        with open(args.input, 'r', encoding='utf-8') as f:
            content = f.read()
    elif args.text:
        content = args.text
    else:
        print("请提供 --input 或 --text 参数")
        exit(1)
    
    # 解析
    result = parse_card_message(content)
    
    # 输出
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print(card_to_markdown(content))
    else:
        print(result["text_content"])
