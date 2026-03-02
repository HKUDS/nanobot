import asyncio
import httpx
import json

async def test():
    print("Testing raw httpx to Zhipu...")
    async with httpx.AsyncClient() as client:
        # First test: Pure curl simulation
        res = await client.post(
            "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer ccaaf7a512aa419b9a836063509967da.pxwq9wd0YavAf6BU",
                "User-Agent": "curl/8.7.1"
            },
            json={
                "model": "glm-5",
                "messages": [{"role": "user", "content": "hello"}]
            }
        )
        print("Test 1 (Curl mode):", res.status_code, res.text)
        
        # Second test: Python user-agent
        res2 = await client.post(
            "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer ccaaf7a512aa419b9a836063509967da.pxwq9wd0YavAf6BU",
                "User-Agent": "python-requests/2.32.3"
            },
            json={
                "model": "glm-5",
                "messages": [{"role": "user", "content": "hello"}]
            }
        )
        print("Test 2 (Python mode):", res2.status_code, res2.text)
        
        # Third test: Curl mode with extra_body
        res3 = await client.post(
            "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer ccaaf7a512aa419b9a836063509967da.pxwq9wd0YavAf6BU",
                "User-Agent": "curl/8.7.1"
            },
            json={
                "model": "glm-5",
                "messages": [{"role": "user", "content": "hello"}],
                "extra_body": {}
            }
        )
        print("Test 3 (extra_body):", res3.status_code, res3.text)

asyncio.run(test())
