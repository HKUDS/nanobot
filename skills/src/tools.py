"""
飞书云文档工具函数 - 供 nanobot MCP 调用
"""
from typing import List, Dict, Optional
from src.client import get_client


def list_docs(parent_node: str = None, page_size: int = 20) -> str:
    """
    列出云文档列表
    
    Args:
        parent_node: 文件夹 token（可选），默认列出根目录
        page_size: 每页数量，默认 20
    
    Returns:
        格式化的文档列表
    """
    client = get_client()
    files = client.list_files(parent_node=parent_node, page_size=page_size)
    
    if not files:
        return "没有找到文档"
    
    result = ["📁 云文档列表：\n"]
    for f in files:
        file_type = {
            "docx": "📄 文档",
            "sheet": "📊 表格",
            "bitable": "📋 多维表格",
            "folder": "📁 文件夹",
            "mindnote": "🧠 思维导图",
        }.get(f.get("type", ""), "📎 文件")
        
        result.append(f"{file_type} {f.get('name', '未命名')}")
        result.append(f"   Token: {f.get('token', 'N/A')}\n")
    
    return "\n".join(result)


def read_doc(file_token: str) -> str:
    """
    读取云文档内容
    
    Args:
        file_token: 文档的 file_token（从文档链接获取）
    
    Returns:
        文档内容
    """
    if not file_token:
        return "❌ 请提供文档的 file_token"
    
    client = get_client()
    
    try:
        content = client.get_file_content(file_token)
        if not content:
            return "📄 文档为空"
        
        # 解析 JSON 内容并转为可读格式
        try:
            import json
            data = json.loads(content)
            # 提取文本内容
            body = data.get("data", {}).get("body", {})
            # 简化输出
            return f"📄 文档内容：\n\n{json.dumps(data, ensure_ascii=False, indent=2)[:5000]}"
        except json.JSONDecodeError:
            return f"📄 文档内容：\n\n{content[:5000]}"
            
    except Exception as e:
        return f"❌ 读取失败: {str(e)}"


def search_docs(keyword: str, page_size: int = 10) -> str:
    """
    搜索云文档（需要知识库权限）
    
    Args:
        keyword: 搜索关键词
        page_size: 返回数量，默认 10
    
    Returns:
        搜索结果
    """
    if not keyword:
        return "❌ 请提供搜索关键词"
    
    client = get_client()
    url = f"{client.BASE_URL}/search/v1/files"
    headers = {"Authorization": f"Bearer {client.get_token()}"}
    params = {
        "query": keyword,
        "page_size": page_size,
        "types": ["docx", "sheet", "bitable"]
    }
    
    import requests
    response = requests.get(url, headers=headers, json=params)
    data = response.json()
    
    if data.get("code") != 0:
        return f"❌ 搜索失败: {data.get('msg')}"
    
    items = data.get("data", {}).get("items", [])
    
    if not items:
        return f"🔍 没有找到包含「{keyword}」的文档"
    
    result = [f"🔍 搜索「{keyword}」结果 ({len(items)}条)：\n"]
    for item in items:
        result.append(f"📄 {item.get('title', '未命名')}")
        result.append(f"   链接: {item.get('url', 'N/A')}\n")
    
    return "\n".join(result)
