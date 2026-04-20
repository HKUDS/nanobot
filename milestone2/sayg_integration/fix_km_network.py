"""
修复 KM 容器网络访问问题

问题：KM 容器内使用 host.docker.internal 可能无法访问宿主机网络
解决：改为使用 Docker 网络别名或直接使用 BFF 容器名
"""

import subprocess
import json

def check_km_container_network():
    """检查 KM 容器的网络配置"""
    print("="*60)
    print("检查 KM 容器网络配置")
    print("="*60)
    
    try:
        # 获取 KM 容器信息
        result = subprocess.run(
            ["docker", "inspect", "knowledge-manager"],
            capture_output=True, text=True, timeout=10, encoding='utf-8'
        )
        
        if result.returncode != 0:
            print(f"❌ 无法获取 KM 容器信息：{result.stderr}")
            return
        
        container_info = json.loads(result.stdout)[0]
        
        # 检查环境变量
        env_vars = container_info.get("Config", {}).get("Env", [])
        bff_url = None
        for env in env_vars:
            if "BFF_BASE_URL" in env:
                bff_url = env
                break
        
        print(f"\nKM 容器环境变量:")
        print(f"  BFF_BASE_URL: {bff_url or '未设置'}")
        
        # 检查网络配置
        network_config = container_info.get("NetworkSettings", {})
        networks = network_config.get("Networks", {})
        
        print(f"\n网络配置:")
        for net_name, net_info in networks.items():
            print(f"  网络：{net_name}")
            print(f"    IP 地址：{net_info.get('IPAddress', 'N/A')}")
            print(f"    网关：{net_info.get('Gateway', 'N/A')}")
        
        # 测试 KM 容器内的网络连通性
        print("\n测试 KM 容器内网络连通性:")
        test_urls = [
            "http://host.docker.internal:8000/health",
            "http://bff:8000/health",  # 如果在同一 Docker 网络
            "http://localhost:8000/health",  # 测试本地
        ]
        
        for url in test_urls:
            try:
                result = subprocess.run(
                    ["docker", "exec", "knowledge-manager", "wget", "-q", "--spider", "--timeout=5", url],
                    capture_output=True, timeout=10
                )
                if result.returncode == 0:
                    print(f"  ✅ {url} 可达")
                else:
                    print(f"  ❌ {url} 不可达")
            except Exception as e:
                print(f"  ❌ {url} 测试失败：{e}")
                
    except Exception as e:
        print(f"❌ 检查失败：{e}")


def check_docker_network():
    """检查 Docker 网络"""
    print("\n" + "="*60)
    print("检查 Docker 网络")
    print("="*60)
    
    try:
        # 列出所有 Docker 网络
        result = subprocess.run(
            ["docker", "network", "ls"],
            capture_output=True, text=True, timeout=10, encoding='utf-8'
        )
        print("\nDocker 网络列表:")
        print(result.stdout)
        
        # 检查 nanobot 网络（如果有）
        result = subprocess.run(
            ["docker", "network", "inspect", "nanobot_network"],
            capture_output=True, text=True, timeout=10, encoding='utf-8'
        )
        if result.returncode == 0:
            network_info = json.loads(result.stdout)[0]
            containers = network_info.get("Containers", {})
            print(f"\nnanobot_network 中的容器:")
            for container_id, container_data in containers.items():
                name = container_data.get("Name", "unknown")
                ipv4 = container_data.get("IPv4Address", "N/A")
                print(f"  {name}: {ipv4}")
    except Exception as e:
        print(f"❌ 检查失败：{e}")


def suggest_fix():
    """提供修复建议"""
    print("\n" + "="*60)
    print("修复建议")
    print("="*60)
    
    print("""
问题诊断：
  KM 容器使用 host.docker.internal 访问 BFF，但在某些 Docker 配置下可能无法解析。

解决方案：

方案 1：使用 Docker 网络别名（推荐）
  1. 确保 KM 和 BFF 在同一 Docker 网络
  2. KM 容器内使用 http://bff:8000 访问 BFF
  3. 启动 KM 时添加：--network nanobot_network

方案 2：使用宿主机 IP
  1. 获取宿主机在 Docker 网络的 IP（通常是网关 IP）
  2. 设置环境变量：KM_BFF_URL=http://172.17.0.1:8000

方案 3：使用 host 网络模式
  1. 启动 KM 时添加：--network host
  2. KM 可以直接访问 localhost:8000

快速修复命令：

# 1. 停止现有 KM 容器
docker stop knowledge-manager
docker rm knowledge-manager

# 2. 重新启动 KM（使用 Docker 网络）
docker run -d ^
  --name knowledge-manager ^
  --network nanobot_network ^
  -e BFF_BASE_URL=http://bff:8000 ^
  -e KM_MERGE_THRESHOLD=5 ^
  -e KM_MERGE_INTERVAL=5 ^
  -v km_data:/app/data ^
  km_image:latest

# 3. 或者使用 host 网络模式（Windows 不支持）
# docker run -d --name knowledge-manager --network host ...

验证修复：
  docker exec knowledge-manager wget -q --spider http://bff:8000/health
  如果返回 0 表示成功
""")


if __name__ == "__main__":
    check_km_container_network()
    check_docker_network()
    suggest_fix()
