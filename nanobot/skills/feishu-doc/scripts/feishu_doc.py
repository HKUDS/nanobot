#!/usr/bin/env python3
"""feishu_doc - 飞书云文档 API

凭据获取优先级: ~/.hiperone/config.json > 环境变量
"""

import argparse
import json
import os
import sys
import time as _time
import requests
from typing import Any, Dict, List, Optional


BASE_URL = "https://open.feishu.cn/open-apis"


def _load_nanobot_config() -> Dict[str, str]:
    config_path = os.path.expanduser("~/.hiperone/config.json")
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
            feishu = config.get("channels", {}).get("feishu", {})
            if feishu.get("enabled"):
                return {"appId": feishu.get("appId"), "appSecret": feishu.get("appSecret")}
    except Exception:
        pass
    return {}


_nanobot_cfg = _load_nanobot_config()
APP_ID = _nanobot_cfg.get("appId") or os.environ.get("NANOBOT_CHANNELS__FEISHU__APP_ID", "")
APP_SECRET = _nanobot_cfg.get("appSecret") or os.environ.get("NANOBOT_CHANNELS__FEISHU__APP_SECRET", "")
_token_cache: Dict[str, Any] = {"token": "", "expires": 0}


def get_tenant_access_token() -> str:
    if not APP_ID or not APP_SECRET:
        raise RuntimeError(
            "缺少飞书凭据，请配置 ~/.hiperone/config.json 或设置环境变量 "
            "NANOBOT_CHANNELS__FEISHU__APP_ID / NANOBOT_CHANNELS__FEISHU__APP_SECRET"
        )
    now = _time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=10)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 Token 失败: {data}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires"] = now + data.get("expire", 7200) - 60
    return _token_cache["token"]


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {get_tenant_access_token()}"}


def _check(data: dict, action: str) -> dict:
    if data.get("code") != 0:
        raise RuntimeError(f"{action}失败: [{data.get('code')}] {data.get('msg', 'Unknown error')}")
    return data.get("data", {})


def _get(path: str, params: Optional[dict] = None, *, timeout: int = 10, action: str = "") -> dict:
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=timeout)
    return _check(resp.json(), action or path)


def _post(path: str, payload: Optional[dict] = None, *, params: Optional[dict] = None,
          timeout: int = 10, action: str = "") -> dict:
    resp = requests.post(f"{BASE_URL}{path}", headers=_headers(), json=payload,
                         params=params, timeout=timeout)
    return _check(resp.json(), action or path)


def _patch(path: str, payload: Optional[dict] = None, *, params: Optional[dict] = None,
           timeout: int = 10, action: str = "") -> dict:
    resp = requests.patch(f"{BASE_URL}{path}", headers=_headers(), json=payload,
                          params=params, timeout=timeout)
    return _check(resp.json(), action or path)


def _delete(path: str, *, params: Optional[dict] = None,
            timeout: int = 10, action: str = "") -> dict:
    resp = requests.delete(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=timeout)
    return _check(resp.json(), action or path)


def _pp(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 云文档 (docx/v1, drive/v1)
# ============================================================

def list_files(parent_node: str = "", page_size: int = 20) -> List[Dict]:
    """获取云文档文件列表"""
    params: Dict[str, Any] = {"page_size": page_size}
    if parent_node:
        params["parent_node"] = parent_node
    data = _get("/drive/v1/files", params, action="获取文件列表")
    return data.get("files", [])


def read_doc(document_id: str) -> str:
    """读取云文档内容，返回 Markdown 格式纯文本"""
    params: Dict[str, Any] = {"page_size": 100}
    all_blocks: List[Dict] = []
    while True:
        data = _get(f"/docx/v1/documents/{document_id}/blocks", params, timeout=15,
                     action="获取文档内容")
        all_blocks.extend(data.get("items", []))
        page_token = data.get("page_token")
        if not page_token:
            break
        params = {"page_size": 100, "page_token": page_token}
    return _extract_text_from_blocks(all_blocks)


def get_doc(document_id: str) -> Dict:
    """获取文档元信息（标题、创建时间、修订版本等）"""
    return _get(f"/docx/v1/documents/{document_id}", action="获取文档信息").get("document", {})


def create_doc(title: str, folder_token: str = "") -> Dict:
    """创建云文档，返回 document_id 和 url"""
    params: Dict[str, Any] = {}
    if folder_token:
        params["folder_token"] = folder_token
    payload: Dict[str, Any] = {"title": title}
    data = _post("/docx/v1/documents", payload, params=params, action="创建文档")
    doc = data.get("document", {})
    return {
        "document_id": doc.get("document_id", ""),
        "revision_id": doc.get("revision_id", 1),
        "title": doc.get("title", title),
        "url": f"https://pgnrxubfqk.feishu.cn/docx/{doc.get('document_id', '')}",
    }


def create_blocks(document_id: str, block_id: str, children: List[Dict], index: int = -1) -> Dict:
    """在文档中创建内容块

    每个 block 的内容 key 必须与 block_type 对应的名称一致:
      {"block_type": 2, "text": {...}}        — 段落
      {"block_type": 3, "heading1": {...}}    — 一级标题
      {"block_type": 4, "heading2": {...}}    — 二级标题
      {"block_type": 12, "bullet": {...}}     — 无序列表
      {"block_type": 13, "ordered": {...}}    — 有序列表
      {"block_type": 15, "quote": {...}}      — 引用
    使用 _make_block(type_name, elements) 自动构造正确格式。
    """
    payload: Dict[str, Any] = {"children": children}
    if index >= 0:
        payload["index"] = index
    data = _post(f"/docx/v1/documents/{document_id}/blocks/{block_id}/children",
                 payload, action="创建内容块")
    return data


def _make_text_element(content: str, bold: bool = False, italic: bool = False) -> Dict:
    """构造一个 text_run 元素"""
    style: Dict[str, Any] = {}
    if bold:
        style["bold"] = True
    if italic:
        style["italic"] = True
    return {"text_run": {"content": content, "text_element_style": style}}


def _parse_inline(text: str) -> List[Dict]:
    """解析行内 Markdown 格式（**加粗**、*斜体*），返回 text_run 元素列表"""
    import re
    elements: List[Dict] = []
    pattern = re.compile(r'(\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|\*(.+?)\*)')
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            elements.append(_make_text_element(text[last:m.start()]))
        if m.group(2):
            elements.append(_make_text_element(m.group(2), bold=True, italic=True))
        elif m.group(3):
            elements.append(_make_text_element(m.group(3), bold=True))
        elif m.group(4):
            elements.append(_make_text_element(m.group(4), italic=True))
        last = m.end()
    if last < len(text):
        elements.append(_make_text_element(text[last:]))
    return elements if elements else [_make_text_element(text)]


_BLOCK_TYPE_MAP = {
    "text": 2, "heading1": 3, "heading2": 4, "heading3": 5,
    "heading4": 6, "heading5": 7, "heading6": 8, "heading7": 9,
    "heading8": 10, "heading9": 11, "bullet": 12, "ordered": 13,
    "code": 14, "quote": 15, "todo": 17, "divider": 22,
}
_BLOCK_TYPE_KEY = {v: k for k, v in _BLOCK_TYPE_MAP.items()}


def _make_block(block_type_name: str, elements: List[Dict]) -> Dict:
    """构造一个飞书文档 block，自动使用正确的 type 编号和 key"""
    bt = _BLOCK_TYPE_MAP[block_type_name]
    return {"block_type": bt, block_type_name: {"elements": elements}}


def _md_line_to_block(line: str) -> Dict:
    """将单行 Markdown 转换为飞书 block 结构"""
    import re
    stripped = line.strip()

    heading_match = re.match(r'^(#{1,6})\s+(.*)', stripped)
    if heading_match:
        level = len(heading_match.group(1))
        name = f"heading{level}"
        return _make_block(name, _parse_inline(heading_match.group(2)))

    if re.match(r'^[-*+]\s+', stripped):
        content = re.sub(r'^[-*+]\s+', '', stripped)
        return _make_block("bullet", _parse_inline(content))

    ordered_match = re.match(r'^\d+[.)]\s+(.*)', stripped)
    if ordered_match:
        return _make_block("ordered", _parse_inline(ordered_match.group(1)))

    if stripped.startswith('>'):
        content = re.sub(r'^>\s*', '', stripped)
        return _make_block("quote", _parse_inline(content))

    return _make_block("text", _parse_inline(stripped))


def markdown_to_blocks(markdown: str) -> List[Dict]:
    """将 Markdown 文本转换为飞书 block 列表

    支持: # 标题(1-4级), - 无序列表, 1. 有序列表, > 引用, **加粗**, *斜体*
    空行跳过。
    """
    blocks = []
    for line in markdown.split("\n"):
        if not line.strip():
            continue
        blocks.append(_md_line_to_block(line))
    return blocks


def create_text_blocks(document_id: str, texts: List[str], block_id: str = "") -> Dict:
    """在文档中批量添加文本段落

    texts: 文本列表，每个元素创建一个段落块
    block_id: 父块 ID，默认为文档根块（即 document_id）
    """
    parent = block_id or document_id
    children = [_make_block("text", [_make_text_element(t)]) for t in texts]
    return create_blocks(document_id, parent, children)


def _batch_create_blocks(document_id: str, blocks: List[Dict], batch_size: int = 50) -> None:
    """分批写入 blocks，每批 batch_size 个，按顺序追加"""
    for i in range(0, len(blocks), batch_size):
        chunk = blocks[i:i + batch_size]
        try:
            create_blocks(document_id, document_id, chunk)
        except RuntimeError:
            for b in chunk:
                try:
                    create_blocks(document_id, document_id, [b])
                except RuntimeError:
                    pass


def create_doc_with_content(title: str, content: str, folder_token: str = "") -> Dict:
    """创建文档并写入 Markdown 内容（优先一次性写入，失败则分批重试）

    content: Markdown 格式文本，支持标题、列表、加粗、斜体、引用
    返回: {document_id, title, url}
    """
    result = create_doc(title, folder_token)
    if not (content and content.strip()):
        return result
    blocks = markdown_to_blocks(content)
    if not blocks:
        return result
    doc_id = result["document_id"]
    try:
        create_blocks(doc_id, doc_id, blocks)
    except RuntimeError:
        _batch_create_blocks(doc_id, blocks)
    return result


def delete_doc(document_id: str) -> Dict:
    """删除云文档（移至回收站）"""
    return _delete(f"/drive/v1/files/{document_id}?type=docx", action="删除文档")


def search_docs(keyword: str, page_size: int = 10) -> List[Dict]:
    """搜索云文档（使用 suite 搜索 API）"""
    payload = {"search_key": keyword, "count": page_size, "offset": 0, "docs_types": []}
    data = _post("/suite/docs-api/search/object", payload, action="搜索文档")
    return data.get("docs_entities", [])


_READ_TEXT_TYPES = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 17}
_READ_PREFIX = {3: "# ", 4: "## ", 5: "### ", 6: "#### ", 12: "- ", 13: "1. "}


def _extract_text_from_elements(elements: list) -> str:
    parts = []
    for elem in elements:
        if "text_run" in elem:
            parts.append(elem["text_run"].get("content", ""))
        elif "text" in elem:
            parts.append(elem["text"].get("content", ""))
    return "".join(parts)


def _extract_text_from_blocks(blocks: list) -> str:
    text_parts = []
    for block in blocks:
        bt = block.get("block_type")
        if bt == 1:
            continue
        if bt == 14:
            text_parts.append("```\n" + block.get("code", {}).get("content", "") + "\n```")
            continue
        if bt not in _READ_TEXT_TYPES:
            continue
        key = _BLOCK_TYPE_KEY.get(bt, "text")
        elements = block.get(key, {}).get("elements", [])
        if not elements:
            elements = block.get("text", {}).get("elements", [])
        text = _extract_text_from_elements(elements)
        if bt == 15:
            text = "\n".join("> " + line for line in text.split("\n"))
        else:
            text = _READ_PREFIX.get(bt, "") + text
        if text:
            text_parts.append(text)
    return "\n".join(text_parts)


# ============================================================
# CLI
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu_doc", description="飞书云文档")
    sub = parser.add_subparsers(dest="action")
    p = sub.add_parser("list", help="列出文件")
    p.add_argument("--parent-node", default="")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("get", help="获取文档元信息")
    p.add_argument("--document-id", required=True)
    p = sub.add_parser("read", help="读取文档")
    p.add_argument("--document-id", required=True)
    p = sub.add_parser("search", help="搜索文档")
    p.add_argument("--keyword", required=True)
    p.add_argument("--limit", type=int, default=10)
    p = sub.add_parser("create", help="创建文档")
    p.add_argument("--title", required=True, help="文档标题")
    p.add_argument("--folder-token", default="", help="目标文件夹 token（可选）")
    p.add_argument("--content", default="", help="Markdown 内容，支持标题/列表/加粗/引用（可选）")
    p.add_argument("--content-file", default="", help="从文件读取 Markdown 内容（可选）")
    p = sub.add_parser("create-block", help="在文档中添加内容块")
    p.add_argument("--document-id", required=True, help="文档 ID")
    p.add_argument("--block-id", default="", help="父块 ID（默认为文档根块）")
    p.add_argument("--texts", required=True, help="JSON 数组，如 [\"段落1\",\"段落2\"]")
    p = sub.add_parser("delete", help="删除文档")
    p.add_argument("--document-id", required=True, help="文档 ID")
    return parser


def _run_cli(args: argparse.Namespace) -> None:
    act = args.action
    if act == "list":
        _pp(list_files(args.parent_node, args.limit))
    elif act == "get":
        _pp(get_doc(args.document_id))
    elif act == "read":
        print(read_doc(args.document_id))
    elif act == "search":
        _pp(search_docs(args.keyword, args.limit))
    elif act == "create":
        content = ""
        if args.content_file:
            with open(args.content_file, "r", encoding="utf-8") as f:
                content = f.read()
        elif args.content:
            content = args.content.replace("\\n", "\n")
        if content:
            result = create_doc_with_content(args.title, content, args.folder_token)
        else:
            result = create_doc(args.title, args.folder_token)
        _pp(result)
    elif act == "create-block":
        texts = json.loads(args.texts)
        _pp(create_text_blocks(args.document_id, texts, args.block_id))
    elif act == "delete":
        _pp(delete_doc(args.document_id))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.action:
        parser.print_help()
        return 1
    try:
        _run_cli(args)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
