"""
飞书卡片消息解析器

解析飞书 Interactive Card 消息为可读文本
"""

from .card_parser import parse_card_message, card_to_markdown, extract_urls_from_text

__version__ = "1.0.0"
__all__ = ["parse_card_message", "card_to_markdown", "extract_urls_from_text"]
