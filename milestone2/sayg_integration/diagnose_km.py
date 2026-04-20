"""
诊断KM容器页表问题
"""
import httpx
import asyncio

BFF_BASE_URL = "http://localhost:8000"

async def diagnose():
    print("=" * 70)
    print("KM容器页表诊断")
    print("=" * 70)
    
    # 1. 获取KM容器URL
    print("\n[1] 获取KM容器URL...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/km-url")
            resp.raise_for_status()
            km_url = resp.json().get("km_url")
            print(f"  KM URL: {km_url}")
    except Exception as e:
        print(f"  失败: {e}")
        return
    
    # 2. 检查KM容器的active_pages
    print("\n[2] 检查KM容器的active_pages...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{km_url}/active_pages")
            resp.raise_for_status()
            data = resp.json()
            pages = data.get("pages", [])
            print(f"  活跃页数: {len(pages)}")
            if pages:
                for p in pages[:3]:
                    print(f"    - {p.get('page_id', 'unknown')}: {p.get('status', 'unknown')}")
    except Exception as e:
        print(f"  失败: {e}")
    
    # 3. 通过BFF检查active_pages
    print("\n[3] 通过BFF检查active_pages...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/active_pages")
            resp.raise_for_status()
            data = resp.json()
            pages = data.get("pages", [])
            print(f"  活跃页数: {len(pages)}")
            if pages:
                for p in pages[:3]:
                    print(f"    - {p.get('page_id', 'unknown')}: {p.get('status', 'unknown')}")
    except Exception as e:
        print(f"  失败: {e}")
    
    # 4. 测试allocate_page
    print("\n[4] 测试allocate_page...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/knowledge-manager/allocate_page",
                json={
                    "agent_id": "test_diagnose",
                    "content": "test content",
                    "content_type": "heap",
                    "metadata": {"test": True}
                }
            )
            resp.raise_for_status()
            data = resp.json()
            page_id = data.get("page_id")
            print(f"  分配成功: page_id={page_id}")
            
            # 再次检查active_pages
            print("\n[5] 检查allocate_page后的active_pages...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{km_url}/active_pages")
                resp.raise_for_status()
                data = resp.json()
                pages = data.get("pages", [])
                print(f"  活跃页数: {len(pages)}")
                if pages:
                    for p in pages[-3:]:
                        print(f"    - {p.get('page_id', 'unknown')}: {p.get('status', 'unknown')}")
    except Exception as e:
        print(f"  失败: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose())
