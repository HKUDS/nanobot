"""
飞书云文档 API 客户端
"""
import os
import json
import requests
from typing import Optional, List, Dict, Any


class FeishuClient:
    """飞书云文档 API 客户端"""
    
    BASE_URL = "https://open.feishu.cn/open-apis"
    
    def __init__(self, app_id: str = None, app_secret: str = None):
        self.app_id = app_id or os.getenv("FEISHU_APP_ID")
        self.app_secret = app_secret or os.getenv("FEISHU_APP_SECRET")
        self._tenant_access_token: Optional[str] = None
    
    def _get_tenant_access_token(self) -> str:
        """获取 tenant_access_token"""
        url = f"{self.BASE_URL}/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()
        
        if data.get("code") != 0:
            raise Exception(f"获取 token 失败: {data.get('msg')}")
        
        return data["tenant_access_token"]
    
    def get_token(self) -> str:
        """获取 access token（带缓存）"""
        if not self._tenant_access_token:
            self._tenant_access_token = self._get_tenant_access_token()
        return self._tenant_access_token
    
    def list_files(self, parent_node: str = None, page_size: int = 20) -> List[Dict]:
        """
        获取文件列表
        
        Args:
            parent_node: 文件夹 token，默认获取根目录
            page_size: 每页数量
        
        Returns:
            文件列表
        """
        url = f"{self.BASE_URL}/drive/v1/files"
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        params = {"page_size": page_size}
        if parent_node:
            params["parent_node"] = parent_node
        
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        
        if data.get("code") != 0:
            raise Exception(f"获取文件列表失败: {data.get('msg')}")
        
        return data.get("data", {}).get("files", [])
    
    def get_file_content(self, file_token: str) -> str:
        """
        获取云文档内容
        
        飞书云文档使用 docx API 获取 blocks
        
        Args:
            file_token: 文档的 document_id
        
        Returns:
            文档内容（纯文本）
        """
        url = f"{self.BASE_URL}/docx/v1/documents/{file_token}/blocks"
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        params = {"page_size": 100}
        
        all_blocks = []
        
        while url:
            response = requests.get(url, headers=headers, params=params if '?' not in url else None)
            data = response.json()
            
            if data.get("code") != 0:
                raise Exception(f"获取文档内容失败: {data.get('msg')}")
            
            blocks = data.get("data", {}).get("items", [])
            all_blocks.extend(blocks)
            
            # 检查是否有分页
            page_token = data.get("data", {}).get("page_token")
            if not page_token:
                break
            
            # 更新 URL 和参数进行下一页请求
            url = f"{self.BASE_URL}/docx/v1/documents/{file_token}/blocks"
            params = {"page_size": 100, "page_token": page_token}
        
        # 提取文本内容
        content = self._extract_text_from_blocks(all_blocks)
        return content
    
    def _extract_text_from_blocks(self, blocks: list) -> str:
        """从 blocks 中提取纯文本"""
        text_parts = []
        
        for block in blocks:
            block_type = block.get("block_type")
            content = ""
            
            # block_type: 1=page, 2=paragraph, 3=heading1, 4=heading2, 5=heading3
            # 7=bulleted, 8=numbered, 10=code, 11=quote, 20=dividor
            
            if block_type == 1:  # page (文档封面)
                # 跳过首页
                continue
            
            elif block_type == 2:  # paragraph
                elements = block.get("paragraph", {}).get("elements", [])
                content = self._extract_text_from_elements(elements)
            
            elif block_type == 3:  # heading1
                elements = block.get("heading1", {}).get("elements", [])
                content = "## " + self._extract_text_from_elements(elements)
            
            elif block_type == 4:  # heading2
                elements = block.get("heading2", {}).get("elements", [])
                content = "### " + self._extract_text_from_elements(elements)
            
            elif block_type == 5:  # heading3
                elements = block.get("heading3", {}).get("elements", [])
                content = "#### " + self._extract_text_from_elements(elements)
            
            elif block_type == 7:  # bulleted list
                elements = block.get("bulleted_list_item", {}).get("elements", [])
                content = "- " + self._extract_text_from_elements(elements)
            
            elif block_type == 8:  # numbered list
                elements = block.get("numbered_list_item", {}).get("elements", [])
                content = "1. " + self._extract_text_from_elements(elements)
            
            elif block_type == 10:  # code
                content = "```\n" + block.get("code", {}).get("content", "") + "\n```"
            
            elif block_type == 11:  # quote
                elements = block.get("quote", {}).get("elements", [])
                lines = self._extract_text_from_elements(elements)
                content = "\n".join(["> " + line for line in lines.split("\n")])
            
            if content:
                text_parts.append(content)
        
        return "\n".join(text_parts)
    
    def _extract_text_from_elements(self, elements: list) -> str:
        """从 elements 中提取文本"""
        parts = []
        for elem in elements:
            if "text_run" in elem:
                parts.append(elem["text_run"].get("content", ""))
            elif "text" in elem:
                parts.append(elem["text"].get("content", ""))
        return "".join(parts)
    
    def export_to_markdown(self, file_token: str) -> str:
        """
        导出文档为 Markdown 格式
        
        Args:
            file_token: 文档的 file_token
        
        Returns:
            Markdown 格式内容
        """
        url = f"{self.BASE_URL}/drive/v1/files/{file_token}/export"
        headers = {"Authorization": f"Bearer {self.get_token()}"}
        params = {"type": "markdown"}
        
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        
        if data.get("code") != 0:
            raise Exception(f"导出 Markdown 失败: {data.get('msg')}")
        
        # 返回导出任务的 token，之后需要轮询获取结果
        return data.get("data", {}).get("token", "")


# 全局客户端实例
_client: Optional[FeishuClient] = None


def get_client() -> FeishuClient:
    """获取全局客户端实例"""
    global _client
    if _client is None:
        _client = FeishuClient()
    return _client
