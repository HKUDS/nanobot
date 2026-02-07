"""Markdown to Feishu post format converter."""

from markdown_it import MarkdownIt
from markdown_it.token import Token


class FeishuMarkdownConverter:
    """Convert markdown to Feishu post format."""

    def __init__(self):
        self.md = MarkdownIt()

    def convert(self, markdown_text: str) -> dict:
        """
        Convert markdown text to Feishu post format.

        Returns a dict suitable for json.dumps() in Feishu message API.
        """
        tokens = self.md.parse(markdown_text)
        content = self._process_tokens(tokens)

        return {
            "zh_cn": {
                "title": "",
                "content": content
            }
        }

    def _process_tokens(self, tokens: list[Token]) -> list[list[dict]]:
        """Process markdown tokens into Feishu content format."""
        content = []
        i = 0

        while i < len(tokens):
            token = tokens[i]

            if token.type == "heading_open":
                # Process heading
                i, line = self._process_heading(tokens, i)
                content.append(line)
            elif token.type == "paragraph_open":
                # Process paragraph
                i, lines = self._process_paragraph(tokens, i)
                content.extend(lines)
            elif token.type == "bullet_list_open":
                # Process unordered list
                i, lines = self._process_list(tokens, i, ordered=False)
                content.extend(lines)
            elif token.type == "ordered_list_open":
                # Process ordered list
                i, lines = self._process_list(tokens, i, ordered=True)
                content.extend(lines)
            elif token.type == "fence" or token.type == "code_block":
                # Process code block
                content.append(self._process_code_block(token))
                i += 1
            elif token.type == "hr":
                # Horizontal rule
                content.append([{"tag": "hr"}])
                i += 1
            else:
                i += 1

        # Ensure at least one line
        if not content:
            content = [[{"tag": "text", "text": ""}]]

        return content

    def _process_heading(self, tokens: list[Token], start_idx: int) -> tuple[int, list[dict]]:
        """Process heading tokens."""
        heading_open = tokens[start_idx]
        level = int(heading_open.tag[1])  # h1 -> 1, h2 -> 2, etc.

        # Get inline content
        inline_idx = start_idx + 1
        inline_token = tokens[inline_idx]

        elements = self._process_inline(inline_token)

        # Make text bold for headings
        for elem in elements:
            if elem.get("tag") == "text":
                elem["style"] = elem.get("style", []) + ["bold"]

        # Skip to closing tag
        next_idx = inline_idx + 2  # skip inline and heading_close

        return next_idx, elements

    def _process_paragraph(self, tokens: list[Token], start_idx: int) -> tuple[int, list[list[dict]]]:
        """Process paragraph tokens."""
        inline_idx = start_idx + 1
        inline_token = tokens[inline_idx]

        elements = self._process_inline(inline_token)

        # Split by newlines to create multiple lines
        lines = []
        current_line = []

        for elem in elements:
            if elem.get("tag") == "text" and "\n" in elem.get("text", ""):
                # Split text by newlines
                parts = elem["text"].split("\n")
                for i, part in enumerate(parts):
                    if part:  # Non-empty part
                        current_line.append({**elem, "text": part})
                    if i < len(parts) - 1:  # Not the last part
                        if current_line:
                            lines.append(current_line)
                        current_line = []
            else:
                current_line.append(elem)

        if current_line:
            lines.append(current_line)

        # Ensure at least one line
        if not lines:
            lines = [[{"tag": "text", "text": ""}]]

        next_idx = inline_idx + 2  # skip inline and paragraph_close
        return next_idx, lines

    def _process_inline(self, inline_token: Token) -> list[dict]:
        """Process inline tokens (text, strong, em, code, link, etc.)."""
        if not inline_token.children:
            return [{"tag": "text", "text": ""}]

        elements = []
        i = 0

        while i < len(inline_token.children):
            child = inline_token.children[i]

            if child.type == "text":
                elements.append({"tag": "text", "text": child.content})
                i += 1
            elif child.type == "code_inline":
                elements.append({"tag": "text", "text": child.content, "style": ["code"]})
                i += 1
            elif child.type == "strong_open":
                # Find matching close
                i, elem = self._process_styled(inline_token.children, i, "strong", ["bold"])
                elements.append(elem)
            elif child.type == "em_open":
                # Find matching close
                i, elem = self._process_styled(inline_token.children, i, "em", ["italic"])
                elements.append(elem)
            elif child.type == "s_open":
                # Strikethrough
                i, elem = self._process_styled(inline_token.children, i, "s", ["lineThrough"])
                elements.append(elem)
            elif child.type == "link_open":
                # Process link
                i, elem = self._process_link(inline_token.children, i)
                elements.append(elem)
            elif child.type == "softbreak" or child.type == "hardbreak":
                elements.append({"tag": "text", "text": "\n"})
                i += 1
            else:
                i += 1

        return elements if elements else [{"tag": "text", "text": ""}]

    def _process_styled(self, children: list[Token], start_idx: int,
                       tag_type: str, styles: list[str]) -> tuple[int, dict]:
        """Process styled text (bold, italic, strikethrough)."""
        text_parts = []
        i = start_idx + 1

        while i < len(children) and children[i].type != f"{tag_type}_close":
            if children[i].type == "text":
                text_parts.append(children[i].content)
            elif children[i].type == "code_inline":
                text_parts.append(children[i].content)
            i += 1

        text = "".join(text_parts)
        elem = {"tag": "text", "text": text, "style": styles}

        return i + 1, elem  # +1 to skip close tag

    def _process_link(self, children: list[Token], start_idx: int) -> tuple[int, dict]:
        """Process link."""
        link_open = children[start_idx]
        href = link_open.attrGet("href") or ""

        # Get link text
        text_parts = []
        i = start_idx + 1

        while i < len(children) and children[i].type != "link_close":
            if children[i].type == "text":
                text_parts.append(children[i].content)
            i += 1

        text = "".join(text_parts) or href
        elem = {"tag": "a", "text": text, "href": href}

        return i + 1, elem  # +1 to skip close tag

    def _process_list(self, tokens: list[Token], start_idx: int,
                     ordered: bool = False) -> tuple[int, list[list[dict]]]:
        """Process list (ordered or unordered)."""
        lines = []
        i = start_idx + 1
        item_num = 1

        close_type = "ordered_list_close" if ordered else "bullet_list_close"

        while i < len(tokens) and tokens[i].type != close_type:
            if tokens[i].type == "list_item_open":
                # Process list item
                i, item_lines = self._process_list_item(tokens, i, ordered, item_num)
                lines.extend(item_lines)
                item_num += 1
            else:
                i += 1

        return i + 1, lines  # +1 to skip close tag

    def _process_list_item(self, tokens: list[Token], start_idx: int,
                          ordered: bool, item_num: int) -> tuple[int, list[list[dict]]]:
        """Process a single list item."""
        i = start_idx + 1
        item_content = []

        while i < len(tokens) and tokens[i].type != "list_item_close":
            if tokens[i].type == "paragraph_open":
                inline_token = tokens[i + 1]
                elements = self._process_inline(inline_token)

                # Add bullet or number prefix
                prefix = f"{item_num}. " if ordered else "• "
                if elements and elements[0].get("tag") == "text":
                    elements[0]["text"] = prefix + elements[0]["text"]
                else:
                    elements.insert(0, {"tag": "text", "text": prefix})

                item_content.append(elements)
                i += 3  # skip paragraph_open, inline, paragraph_close
            else:
                i += 1

        return i + 1, item_content  # +1 to skip list_item_close

    def _process_code_block(self, token: Token) -> list[dict]:
        """Process code block."""
        language = token.info or ""
        code = token.content.rstrip("\n")

        return [{"tag": "code_block", "text": code, "language": language}]


def should_render_markdown(text: str) -> bool:
    """
    Determine if text contains markdown that should be rendered.

    Returns True if text contains markdown syntax, False for plain text.
    """
    markdown_indicators = [
        "```",  # code blocks
        "**",   # bold
        "__",   # bold
        "*",    # italic/bold
        "_",    # italic
        "[",    # links
        "#",    # headings
        "-",    # lists
        "1.",   # ordered lists
        ">",    # blockquotes
        "`",    # inline code
    ]

    return any(indicator in text for indicator in markdown_indicators)
