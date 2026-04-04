---
name: "container-api-fix"
description: "Fixes Docker container network API call issues in WSL environment. Invoke when container fails to call external APIs due to proxy/network problems."
---

# Container API Fix Skill

## 问题场景

当 Docker 容器内的 nanobot agent 无法调用外部 API（如 DeepSeek、OpenAI）时，表现为：
- `LLM transient error: connection error`
- `LLM transient error: request timed out`
- 容器健康检查正常，但 API 调用失败

## 根因分析

WSL2 环境下的网络代理配置问题：
1. WSL 会自动继承 Windows 的代理设置（`http_proxy`、`https_proxy`）
2. Docker 容器会继承宿主机的代理环境变量
3. 如果代理配置不正确或代理服务器不可达，容器内网络请求会失败

## 解决方案

### 方案 1：在 BFF 中为容器设置代理环境变量（推荐）

修改 `container_orchestrator.py`，在创建容器时注入代理环境变量：

```python
class ContainerOrchestrator:
    def __init__(self, ...):
        # 从宿主机读取代理配置
        self.http_proxy = os.environ.get('http_proxy')
        self.https_proxy = os.environ.get('https_proxy')
        self.no_proxy = os.environ.get('no_proxy', 'localhost,127.0.0.1,::1')
    
    async def create_container(self, conversation_id: str, ...):
        # 构建环境变量
        environment = {
            "CONVERSATION_ID": conversation_id,
            "TASK": task,
            "MODEL": model,
            "API_KEY": api_key,
            "WORKSPACE_DIR": "/app/workspace",
        }
        
        # 注入代理环境变量（大小写都设置，兼容不同库）
        if self.http_proxy:
            environment["HTTP_PROXY"] = self.http_proxy
            environment["http_proxy"] = self.http_proxy
        if self.https_proxy:
            environment["HTTPS_PROXY"] = self.https_proxy
            environment["https_proxy"] = self.https_proxy
        if self.no_proxy:
            environment["NO_PROXY"] = self.no_proxy
            environment["no_proxy"] = self.no_proxy
        
        # 创建容器时传入环境变量
        container = self.docker_client.containers.run(
            image=self.image_name,
            name=container_name,
            environment=environment,
            ...
        )
```

### 方案 2：在 agent_server.py 中读取代理环境变量

在容器内的 agent 启动时，确保代理环境变量被正确设置：

```python
async def initialize_agent():
    global agent_instance
    try:
        # 确保代理环境变量被正确设置（大小写都设置，供不同库使用）
        http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
        https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
        no_proxy = os.environ.get('NO_PROXY') or os.environ.get('no_proxy')
        
        if http_proxy:
            os.environ['HTTP_PROXY'] = http_proxy
            os.environ['http_proxy'] = http_proxy
        if https_proxy:
            os.environ['HTTPS_PROXY'] = https_proxy
            os.environ['https_proxy'] = https_proxy
        if no_proxy:
            os.environ['NO_PROXY'] = no_proxy
            os.environ['no_proxy'] = no_proxy
        
        # 设置 DeepSeek 的 base URL
        os.environ['OPENAI_BASE_URL'] = 'https://api.deepseek.com/v1'
        
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        provider = OpenAICompatProvider(api_key=api_key)
        
        # ... 其余初始化代码
```

### 方案 3：临时测试 - 在 WSL 中取消代理

如果只是测试，可以在 WSL 中临时取消代理：

```bash
unset http_proxy https_proxy
```

**注意**：这只是临时方案，容器重启后会失效。

## 验证步骤

1. **检查容器环境变量**：
   ```bash
   docker exec nanobot_conv_<id> env | grep -i proxy
   ```

2. **测试容器内网络连通性**：
   ```bash
   docker exec nanobot_conv_<id> curl -I https://api.deepseek.com
   ```

3. **查看容器日志**：
   ```bash
   docker logs nanobot_conv_<id>
   ```
   应该看到：
   ```
   [Agent] Proxy settings: HTTP_PROXY=http://..., HTTPS_PROXY=http://...
   ```

4. **测试 API 调用**：
   ```bash
   curl -X POST http://localhost:<port>/chat -H "Content-Type: application/json" -d '{"content":"Hello"}'
   ```

## 完整代码示例

### container_orchestrator.py 修改

```python
import os
from docker import DockerClient
from docker.models.containers import Container

class ContainerOrchestrator:
    """Manages Docker containers for Nanobot agents."""
    
    def __init__(
        self,
        image_name: str = "nanobot-agent:latest",
        volume_prefix: str = "nanobot_workspace_",
        memory_limit: str = "512m",
        cpu_limit: float = 0.5,
    ):
        self.docker_client = DockerClient()
        self.image_name = image_name
        self.volume_prefix = volume_prefix
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        
        # 从宿主机读取代理配置
        self.http_proxy = os.environ.get('http_proxy')
        self.https_proxy = os.environ.get('https_proxy')
        self.no_proxy = os.environ.get('no_proxy', 'localhost,127.0.0.1,::1')
        
        print(f"[Orchestrator] Proxy config: HTTP={self.http_proxy}, HTTPS={self.https_proxy}")
    
    async def create_container(
        self,
        conversation_id: str,
        task: str = "",
        model: str = "deepseek-chat",
        api_key: str = "",
    ) -> dict:
        """Create and start a new container for a conversation."""
        container_name = self._get_container_name(conversation_id)
        volume_name = self._get_volume_name(conversation_id)
        
        # 构建环境变量
        environment = {
            "CONVERSATION_ID": conversation_id,
            "TASK": task,
            "MODEL": model,
            "API_KEY": api_key,
            "WORKSPACE_DIR": "/app/workspace",
        }
        
        # 注入代理环境变量
        if self.http_proxy:
            environment["HTTP_PROXY"] = self.http_proxy
            environment["http_proxy"] = self.http_proxy
        if self.https_proxy:
            environment["HTTPS_PROXY"] = self.https_proxy
            environment["https_proxy"] = self.https_proxy
        if self.no_proxy:
            environment["NO_PROXY"] = self.no_proxy
            environment["no_proxy"] = self.no_proxy
        
        # 创建容器
        container = self.docker_client.containers.run(
            image=self.image_name,
            name=container_name,
            volumes={volume_name: {"bind": "/app/workspace", "mode": "rw"}},
            environment=environment,
            mem_limit=self.memory_limit,
            cpu_period=100000,
            cpu_quota=int(self.cpu_limit * 100000),
            ports={"8080/tcp": None},  # 动态分配端口
            detach=True,
        )
        
        # 等待容器就绪
        await self._wait_until_ready(container)
        
        # 获取分配的端口
        container.reload()
        port = container.ports["8080/tcp"][0]["HostPort"]
        
        return {
            "container_id": container.id,
            "container_name": container_name,
            "port": port,
            "volume_name": volume_name,
        }
```

### agent_server.py 修改

```python
async def initialize_agent():
    global agent_instance
    try:
        # 确保代理环境变量被正确设置（大小写都设置，供不同库使用）
        http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
        https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
        no_proxy = os.environ.get('NO_PROXY') or os.environ.get('no_proxy')
        
        if http_proxy:
            os.environ['HTTP_PROXY'] = http_proxy
            os.environ['http_proxy'] = http_proxy
        if https_proxy:
            os.environ['HTTPS_PROXY'] = https_proxy
            os.environ['https_proxy'] = https_proxy
        if no_proxy:
            os.environ['NO_PROXY'] = no_proxy
            os.environ['no_proxy'] = no_proxy
        
        # 设置 DeepSeek 的 base URL（OpenAICompatProvider 会读取）
        os.environ['OPENAI_BASE_URL'] = 'https://api.deepseek.com/v1'
        
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        from nanobot.agent.tools.registry import ToolRegistry
        from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
        from nanobot.agent.tools.message import MessageTool
        
        api_key = os.environ.get("API_KEY", "")
        model = os.environ.get("MODEL", "deepseek-chat")
        
        provider = OpenAICompatProvider(api_key=api_key)
        
        tool_registry = ToolRegistry()
        tool_registry.register(WebSearchTool())
        tool_registry.register(WebFetchTool())
        tool_registry.register(MessageTool())
        
        agent_instance = {
            "provider": provider,
            "tool_registry": tool_registry,
            "model": model,
        }
        
        print(f"[Agent] Initialized for conversation={CONVERSATION_ID}, model={model}")
        print(f"[Agent] Proxy settings: HTTP_PROXY={os.environ.get('HTTP_PROXY')}, HTTPS_PROXY={os.environ.get('HTTPS_PROXY')}")
    except Exception as e:
        print(f"[Agent] Initialization error: {e}")
        raise
```

## 常见问题

### Q: 为什么需要同时设置大写和小写的环境变量？

A: 不同的 Python 库使用不同的环境变量命名：
- `requests` 库使用小写：`http_proxy`、`https_proxy`
- `urllib3` 和一些其他库使用大写：`HTTP_PROXY`、`HTTPS_PROXY`
- 同时设置两者可以确保兼容性

### Q: 代理地址应该是什么格式？

A: 通常是 `http://host:port` 格式，例如：
- Windows 本地代理：`http://127.0.0.1:7890`
- WSL 中访问 Windows 代理：`http://172.27.160.1:7890`（WSL 的 Windows 主机 IP）

### Q: NO_PROXY 是什么？

A: `NO_PROXY` 指定哪些地址不走代理，通常包括：
- `localhost`、`127.0.0.1`：本地回环地址
- `::1`：IPv6 本地地址
- 内网地址段（如需要）：`192.168.0.0/16`

### Q: 如何知道 WSL 中的代理配置是什么？

A: 在 WSL 中运行：
```bash
echo $http_proxy
echo $https_proxy
env | grep -i proxy
```

## 参考资料

- [Docker 容器网络配置](https://docs.docker.com/config/containers/container-networking/)
- [WSL2 网络架构](https://docs.microsoft.com/en-us/windows/wsl/networking)
- [Python requests 代理配置](https://requests.readthedocs.io/en/latest/user/advanced/#proxies)
