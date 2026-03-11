#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feishu Document Converter - 文档格式转换
支持：文档→MD，URL→MD
"""

import os
import re
import requests
from typing import Dict, Optional


def load_config():
    """从环境变量加载飞书配置"""
    config = {
        'FEISHU_APP_ID': os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_ID', ''),
        'FEISHU_APP_SECRET': os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_SECRET', ''),
        'FEISHU_API_DOMAIN': os.environ.get('FEISHU_API_DOMAIN', 'https://open.feishu.cn'),
        'FEISHU_WIKI_SPACE_ID': os.environ.get('FEISHU_WIKI_SPACE_ID', '7313882962775556100'),
    }
    if not config['FEISHU_APP_ID'] or not config['FEISHU_APP_SECRET']:
        raise Exception("缺少飞书凭据，请设置环境变量 NANOBOT_CHANNELS__FEISHU__APP_ID / NANOBOT_CHANNELS__FEISHU__APP_SECRET")
    return config


def get_access_token(config: Dict) -> str:
    """获取 tenant_access_token"""
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    payload = {
        "app_id": config['FEISHU_APP_ID'],
        "app_secret": config['FEISHU_APP_SECRET']
    }
    response = requests.post(url, json=payload, headers=headers)
    result = response.json()
    if result.get("code") == 0:
        return result["tenant_access_token"]
    raise Exception(f"获取token失败: {result}")


def extract_doc_id(doc_ref: str) -> tuple:
    """
    从文档引用中提取文档信息
    支持：云盘URL、知识库URL、docx/xxx、纯ID
    
    Returns:
        (doc_id, doc_type) 其中 doc_type: "docx" | "wiki"
    """
    # 云盘文档: https://feishu.cn/docx/xxx
    if 'feishu.cn/docx/' in doc_ref:
        match = re.search(r'docx/([a-zA-Z0-9]+)', doc_ref)
        if match:
            return match.group(1), "docx"
    
    # 知识库文档: https://xxx.feishu.cn/wiki/xxx
    if 'feishu.cn/wiki/' in doc_ref:
        match = re.search(r'wiki/([a-zA-Z0-9]+)', doc_ref)
        if match:
            return match.group(1), "wiki"
    
    # docx/xxx 格式
    if doc_ref.startswith('docx/'):
        return doc_ref[5:], "docx"
    
    # 假设是纯ID（默认按云盘文档处理）
    return doc_ref, "docx"


def _get_wiki_obj_token(token: str, config: dict, node_token: str) -> str:
    """通过知识库 node_token 获取 obj_token"""
    space_id = config.get('FEISHU_WIKI_SPACE_ID', '7313882962775556100')
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/wiki/v2/spaces/{space_id}/nodes/{node_token}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        error_text = response.text[:500]
        raise Exception(
            f"无法访问知识库文档。可能的原因:\n"
            f"1. 文档属于外部知识库空间，无权限访问\n"
            f"2. 文档不存在或已被删除\n"
            f"3. 应用没有 wiki:wiki 权限\n"
            f"\n技术详情: HTTP {response.status_code}, {error_text}"
        )
    
    try:
        result = response.json()
    except Exception as e:
        raise Exception(f"解析响应失败: {e}, 原始响应: {response.text[:500]}")
    
    if result.get("code") != 0:
        raise Exception(f"获取知识库节点失败: {result}")
    
    obj_token = result["data"]["node"]["obj_token"]
    return obj_token


def doc_to_md(doc_ref: str, use_browser: bool = False) -> str:
    """
    将飞书文档转为 Markdown
    
    Args:
        doc_ref: 文档ID或URL（支持云盘 docx 和知识库 wiki）
        use_browser: 是否强制使用 browser 方式（默认自动判断）
    
    Returns:
        Markdown 字符串
    """
    doc_id, doc_type = extract_doc_id(doc_ref)
    
    # 知识库文档默认使用 browser 方式（避免权限问题）
    if doc_type == "wiki" or use_browser:
        return _doc_to_md_by_browser(doc_ref)
    
    # 云盘文档使用 API 方式
    config = load_config()
    token = get_access_token(config)
    
    # 获取文档内容
    blocks = _get_document_blocks(token, config, doc_id)
    
    # 转换为 Markdown
    md_content = _blocks_to_md(blocks)
    
    return md_content


def _doc_to_md_by_browser(doc_url: str) -> str:
    """
    使用 browser 方式提取文档内容（适用于知识库和外部文档）
    
    Args:
        doc_url: 文档完整 URL
    
    Returns:
        Markdown 字符串
    """
    raise NotImplementedError(
        "Browser 方式提取文档内容需要外部 browser 工具。\n"
        "请使用以下方式之一：\n"
        "1. 调用 browser.open() 访问文档 URL\n"
        "2. 使用 url_to_md() 函数（会尝试 browser 方式）\n"
        f"文档 URL: {doc_url}"
    )
    
    # 转换为 Markdown
    md_content = _blocks_to_md(blocks)
    
    return md_content


def _get_document_blocks(token: str, config: dict, document_id: str) -> list:
    """获取文档的所有内容块"""
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/docx/v1/documents/{document_id}/blocks"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    all_blocks = []
    page_token = None
    
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        
        response = requests.get(url, headers=headers, params=params)
        result = response.json()
        
        if result.get("code") != 0:
            raise Exception(f"获取文档内容失败: {result}")
        
        items = result["data"].get("items", [])
        all_blocks.extend(items)
        
        # 检查是否有更多内容
        has_more = result["data"].get("has_more", False)
        if not has_more:
            break
        
        page_token = result["data"].get("page_token")
    
    return all_blocks


def _blocks_to_md(blocks: list) -> str:
    """将飞书文档块转换为 Markdown"""
    md_lines = []
    
    for block in blocks:
        block_type = block.get("block_type")
        
        # 文本块
        if block_type == 2:
            text_content = _extract_text_content(block.get("text", {}))
            if text_content:
                md_lines.append(text_content)
        
        # 标题块 (3-11: heading1-9)
        elif 3 <= block_type <= 11:
            level = block_type - 2
            text_content = _extract_text_content(block.get(f"heading{level}", {}))
            if text_content:
                md_lines.append(f"{'#' * level} {text_content}")
        
        # 无序列表
        elif block_type == 12:
            text_content = _extract_text_content(block.get("bullet", {}))
            if text_content:
                md_lines.append(f"- {text_content}")
        
        # 有序列表
        elif block_type == 13:
            text_content = _extract_text_content(block.get("ordered", {}))
            if text_content:
                md_lines.append(f"1. {text_content}")
        
        # 代码块
        elif block_type == 14:
            code_content = _extract_text_content(block.get("code", {}))
            lang = block.get("code", {}).get("style", {}).get("language", "")
            md_lines.append(f"```{lang}\n{code_content}\n```")
        
        # 引用块
        elif block_type == 15:
            text_content = _extract_text_content(block.get("quote", {}))
            if text_content:
                md_lines.append(f"> {text_content}")
        
        # 待办事项
        elif block_type == 17:
            text_content = _extract_text_content(block.get("todo", {}))
            done = block.get("done", False)
            checkbox = "[x]" if done else "[ ]"
            if text_content:
                md_lines.append(f"- {checkbox} {text_content}")
        
        # 分割线
        elif block_type == 22:
            md_lines.append("---")
        
        # 表格 (31)
        elif block_type == 31:
            table_md = _convert_table(block)
            if table_md:
                md_lines.append(table_md)
    
    return "\n\n".join(md_lines)


def _extract_text_content(text_block: dict) -> str:
    """从文本块中提取纯文本内容"""
    elements = text_block.get("elements", [])
    texts = []
    
    for elem in elements:
        if "text_run" in elem:
            text = elem["text_run"].get("content", "")
            style = elem["text_run"].get("text_element_style", {})
            
            # 处理样式
            if style.get("bold"):
                text = f"**{text}**"
            if style.get("italic"):
                text = f"*{text}*"
            if style.get("underline"):
                text = f"<u>{text}</u>"
            if style.get("strikethrough"):
                text = f"~~{text}~~"
            
            texts.append(text)
        elif "mention" in elem:
            # 提及用户
            texts.append(f"@{elem['mention'].get('name', '')}")
        elif "link" in elem:
            # 链接
            url = elem["link"].get("url", "")
            text = elem["link"].get("content", url)
            texts.append(f"[{text}]({url})")
    
    return "".join(texts)


def _convert_table(block: dict) -> str:
    """将表格块转换为 Markdown 表格"""
    # 表格处理比较复杂，需要获取单元格内容
    # 这里先返回占位符
    return "<!-- 表格内容需手动处理 -->"


def _zhihu_to_md(url: str) -> str:
    """知乎文章转 Markdown（待实现）"""
    raise NotImplementedError("知乎文章抓取待实现")


def url_to_md(url: str) -> str:
    """
    将外部链接转为 Markdown
    支持：微信公众号、飞书文档（知识库/云盘）、知乎等
    
    Args:
        url: 文章链接
    
    Returns:
        Markdown 字符串
    """
    # 飞书文档（知识库或云盘）
    if 'feishu.cn' in url:
        return _feishu_doc_to_md_by_browser(url)
    
    # 微信公众号
    if 'mp.weixin.qq.com' in url:
        return _wechat_to_md(url)
    
    # 知乎
    if 'zhihu.com' in url or 'zhuanlan.zhihu.com' in url:
        return _zhihu_to_md(url)
    
    # 其他网页
    return _generic_url_to_md(url)


def _feishu_doc_to_md_by_browser(url: str) -> str:
    """
    使用 browser 方式提取飞书文档内容
    适用于知识库文档（包括外部知识库）和云盘文档
    """
    # 检查是否是知识库 URL
    if '/wiki/' in url:
        doc_type = "知识库文档"
    elif '/docx/' in url:
        doc_type = "云盘文档"
    else:
        doc_type = "飞书文档"
    
    # 由于无法直接调用 browser 工具，提供指导
    return (
        f"<!-- {doc_type}内容提取指南 -->\n\n"
        f"文档 URL: {url}\n\n"
        f"由于飞书文档需要登录态访问，请使用以下方式提取内容：\n\n"
        f"**方式1：使用 browser 工具（推荐）**\n"
        f"```\n"
        f"browser.open(\"{url}\")\n"
        f"content = browser.extract_text()\n"
        f"```\n\n"
        f"**方式2：手动复制**\n"
        f"1. 在浏览器中打开文档\n"
        f"2. 复制内容到 Markdown 文件\n\n"
        f"**方式3：使用飞书导出功能**\n"
        f"1. 在飞书客户端打开文档\n"
        f"2. 点击右上角 ... → 导出为 Markdown\n"
    )


def _wechat_to_md(url: str) -> str:
    """微信公众号文章转 Markdown"""
    try:
        import sys
        _ce_dir = str(Path(__file__).parent.parent / 'content-extractor')
        if _ce_dir not in sys.path:
            sys.path.insert(0, _ce_dir)
        from wechat_fetcher import WechatArticleFetcher
        
        fetcher = WechatArticleFetcher()
        article = fetcher.fetch(url)
        
        md = f"# {article.get('title', '')}\n\n"
        md += f"**作者**: {article.get('author', '未知')}\n\n"
        if article.get('publish_time'):
            md += f"**发布时间**: {article.get('publish_time')}\n\n"
        md += "---\n\n"
        md += article.get('content', '')
        
        return md
    except ImportError:
        raise ImportError(
            "wechat_fetcher 未找到。\n"
            "请确保 skills/content-extractor/wechat_fetcher.py 存在。"
        )


def _zhihu_to_md(url: str) -> str:
    """知乎文章转 Markdown（待实现）"""
    raise NotImplementedError("知乎文章抓取待实现")


def _generic_url_to_md(url: str) -> str:
    """通用网页转 Markdown（待实现）"""
    raise NotImplementedError(
        "通用网页抓取待实现。\n"
        "建议使用 browser 工具访问页面并提取内容。"
    )


# 便捷函数
def convert(source: str, source_type: str = "auto") -> str:
    """
    统一转换入口
    
    Args:
        source: 文档ID/URL/链接
        source_type: "doc" | "url" | "auto"
    
    Returns:
        Markdown 字符串
    """
    if source_type == "auto":
        # 自动判断类型
        if 'feishu.cn' in source or source.startswith('docx/'):
            source_type = "doc"
        else:
            source_type = "url"
    
    if source_type == "doc":
        return doc_to_md(source)
    elif source_type == "url":
        return url_to_md(source)
    else:
        raise ValueError(f"不支持的源类型: {source_type}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("用法: python feishu_doc_converter.py <doc|url> <source> [output.md]")
        print("  doc: 飞书文档ID或URL")
        print("  url: 外部文章链接")
        sys.exit(1)
    
    source_type = sys.argv[1]
    source = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) >= 4 else None
    
    try:
        md_content = convert(source, source_type)
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(md_content)
            print(f"已保存到: {output_file}")
        else:
            print(md_content)
    except Exception as e:
        print(f"转换失败: {e}")
        sys.exit(1)
