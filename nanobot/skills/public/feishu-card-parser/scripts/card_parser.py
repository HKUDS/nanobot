#!/usr/bin/env python3
"""
飞书卡片消息解析器
Parse Feishu/Lark interactive card messages to readable text
"""

import json
import re
import argparse
from typing import List, Dict, Any, Union


def parse_card_message(card_content: Union[str, Dict]) -> Dict[str, Any]:
    """Parse Feishu card message JSON to structured data"""
    
    # Parse JSON if string
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
    
    # Extract title
    if "title" in card:
        result["title"] = card["title"]
    
    # Parse content blocks
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
                    md_parts.append(f"\n![image]({image_key})\n")
                    
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
                url = element.get("url", "")
                title = element.get("title", "")
                if url:
                    result["links"].append(url)
                    md_parts.append(f"\n[{title or url}]({url})\n")
    
    result["text_content"] = "".join(text_parts).strip()
    result["markdown_content"] = "".join(md_parts).strip()
    
    return result


def apply_markdown_style(text: str, styles: List[str]) -> str:
    """Apply Markdown formatting based on style tags"""
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
    """Convert card to Markdown format"""
    result = parse_card_message(card_content)
    
    lines = []
    
    if result["title"]:
        lines.append(f"# {result['title']}\n")
    
    if result["markdown_content"]:
        lines.append(result["markdown_content"])
    
    if result["images"]:
        lines.append("\n---\n**Images:**")
        for img in result["images"]:
            lines.append(f"- `{img}`")
    
    if result["links"]:
        lines.append("\n**Links:**")
        for link in result["links"]:
            lines.append(f"- {link}")
    
    if result["mentions"]:
        lines.append("\n**Mentions:**")
        for mention in result["mentions"]:
            lines.append(f"- @{mention['name']} ({mention['id']})")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Parse Feishu card messages")
    parser.add_argument("--input", "-i", help="Input JSON file path")
    parser.add_argument("--text", "-t", help="Raw JSON string")
    parser.add_argument("--format", "-f", choices=["json", "markdown", "text"], 
                        default="markdown", help="Output format")
    
    args = parser.parse_args()
    
    if args.input:
        with open(args.input, 'r', encoding='utf-8') as f:
            content = f.read()
    elif args.text:
        content = args.text
    else:
        print("Error: Provide --input or --text")
        exit(1)
    
    result = parse_card_message(content)
    
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print(card_to_markdown(content))
    else:
        print(result["text_content"])


if __name__ == "__main__":
    main()
