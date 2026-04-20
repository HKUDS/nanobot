"""
重启并修复吞吐量实验系统

步骤：
1. 清理旧容器
2. 重启 BFF（会自动启动 KM 和 Consolidator）
3. 验证系统健康
4. 重新运行实验
"""

import subprocess
import time
import httpx
import asyncio

BFF_BASE_URL = "http://localhost:8000"


def run_cmd(cmd: list, timeout: int = 30) -> bool:
    """运行命令并返回是否成功"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8')
        if result.returncode == 0:
            print(f"✅ {' '.join(cmd)}")
            return True
        else:
            print(f"❌ {' '.join(cmd)}: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ {' '.join(cmd)}: {e}")
        return False


def cleanup_old_containers():
    """清理旧容器"""
    print("\n" + "="*60)
    print("步骤 1: 清理旧容器")
    print("="*60)
    
    # 停止并删除所有 nanobot_conv_* 容器
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=nanobot_conv", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=10, encoding='utf-8'
    )
    
    containers = result.stdout.strip().split('\n') if result.stdout.strip() else []
    
    for container in containers:
        if container:
            run_cmd(["docker", "stop", container])
            run_cmd(["docker", "rm", container])
    
    # 清理 KM、Consolidator、BFF（如果存在）
    for name in ["knowledge-manager", "consolidator", "bff-service"]:
        run_cmd(["docker", "stop", name])
        run_cmd(["docker", "rm", name])
    
    time.sleep(2)


async def wait_for_service(name: str, url: str, timeout: int = 60) -> bool:
    """等待服务就绪"""
    print(f"\n等待 {name} 就绪...")
    start = time.time()
    
    while time.time() - start < timeout:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    print(f"✅ {name} 已就绪（耗时 {time.time()-start:.1f}s）")
                    return True
        except Exception:
            pass
        await asyncio.sleep(2)
    
    print(f"❌ {name} 未就绪（超时 {timeout}s）")
    return False


async def restart_bff():
    """重启 BFF 服务"""
    print("\n" + "="*60)
    print("步骤 2: 重启 BFF 服务")
    print("="*60)
    
    # 这里假设 BFF 是通过某个脚本启动的
    # 实际使用时需要替换为真实的启动命令
    print("请手动启动 BFF 服务，或使用以下命令:")
    print("  python start_bff.py")
    print("  或")
    print("  docker-compose up -d bff")
    
    # 等待 BFF 就绪
    if not await wait_for_service("BFF", f"{BFF_BASE_URL}/health"):
        return False
    
    # 等待 KM 就绪
    if not await wait_for_service("KM", f"{BFF_BASE_URL}/knowledge-manager/health"):
        return False
    
    # 等待 Consolidator 就绪
    if not await wait_for_service("Consolidator", f"{BFF_BASE_URL}/consolidator/health"):
        return False
    
    return True


def verify_system():
    """验证系统健康"""
    print("\n" + "="*60)
    print("步骤 3: 验证系统健康")
    print("="*60)
    
    # 检查容器
    result = subprocess.run(
        ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}"],
        capture_output=True, text=True, timeout=10, encoding='utf-8'
    )
    print("\n运行中的容器:")
    print(result.stdout)
    
    # 检查 PublicMemory
    try:
        import asyncio
        async def check():
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{BFF_BASE_URL}/knowledge-manager/public-memory")
                if resp.status_code == 200:
                    entries = resp.json().get("entries", [])
                    print(f"\nPublicMemory 条目数：{len(entries)}")
                    return len(entries)
        pm_count = asyncio.run(check())
        print(f"✅ PublicMemory: {pm_count} 条")
    except Exception as e:
        print(f"❌ 无法检查 PublicMemory: {e}")


def main():
    print("="*60)
    print("重启吞吐量实验系统")
    print("="*60)
    
    # 1. 清理
    cleanup_old_containers()
    
    # 2. 重启 BFF（需要手动或自动）
    print("\n请启动 BFF 服务...")
    input("启动后按回车继续...")
    
    # 3. 验证
    asyncio.run(restart_bff())
    verify_system()
    
    print("\n" + "="*60)
    print("系统已就绪，可以运行吞吐量实验")
    print("="*60)
    print("\n运行命令:")
    print("  python run_throughput_comparison.py")


if __name__ == "__main__":
    main()
