import os
import aiohttp
from typing import List

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_EMBED_URL = "https://api.deepseek.com/v1/embeddings"
EMBED_MODEL = "deepseek-embedding-v1"


def _get_proxy_connector():
    """获取代理连接器，如果配置了代理则使用代理"""
    http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    
    if https_proxy:
        print(f"[DeepSeekEmbedding] 使用代理: {https_proxy}")
        return aiohttp.ProxyConnector.from_url(https_proxy, ssl=False)
    
    return None


class DeepSeekEmbedding:
    def __init__(self, api_key: str = DEEPSEEK_API_KEY):
        self.api_key = api_key

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        
        connector = _get_proxy_connector()
        
        async with aiohttp.ClientSession(connector=connector) as session:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "input": texts,
                "model": EMBED_MODEL
            }
            
            kwargs = {
                "url": DEEPSEEK_EMBED_URL,
                "json": payload,
                "headers": headers
            }
            
            proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
            if proxy:
                kwargs["proxy"] = proxy
            
            async with session.post(**kwargs) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"DeepSeek Embedding API error: {resp.status} {error_text}")
                data = await resp.json()
                return [item["embedding"] for item in data["data"]]

    async def embed_text(self, text: str) -> List[float]:
        embeddings = await self.embed_texts([text])
        return embeddings[0]
