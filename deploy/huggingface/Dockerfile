# 使用高效的 uv 镜像作为基础
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# 1. 基础环境安装 (针对军团协作优化)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg git bubblewrap openssh-client python3 python3-pip \
    libssl-dev libffi-dev python3-dev build-essential && \
    \
    # --- 关键组件：安装用于 WebSocket 调试的 websocat ---
    curl -L https://github.com/vi/websocat/releases/latest/download/websocat.x86_64-unknown-linux-musl -o /usr/local/bin/websocat && \
    chmod +x /usr/local/bin/websocat && \
    \
    # --- 安装 Node.js (用于编译 WebUI 和 Bridge) ---
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. 预安装基础依赖 (利用 Docker 缓存)
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p nanobot bridge && touch nanobot/__init__.py && \
    uv pip install --system --no-cache ".[matrix]" && \
    rm -rf nanobot bridge

# 3. 复制完整源码及“军团指挥链”核心脚本
COPY nanobot/ nanobot/
COPY bridge/ bridge/
COPY webui/ webui/ 
# 注入军团三大核心脚本
COPY deploy/huggingface/gatekeeper.py ./gatekeeper.py
COPY deploy/huggingface/squad_bridge.py ./squad_bridge.py
COPY deploy/huggingface/squad_config_sync.py ./squad_config_sync.py
COPY deploy/huggingface/patch_bootstrap_peers.py /tmp/patch_bootstrap_peers.py

# 4. 【内核协议适配】：解决 Host 绑定、鉴权及静态路径问题
RUN echo "💉 [Build Surgery] 执行内核协议适配..." && \
    sed -i 's/config.gateway.host/"0.0.0.0"/g' nanobot/cli/commands.py && \
    sed -i 's/host = host if host is not None else api_cfg.host/host = "0.0.0.0"/g' nanobot/cli/commands.py && \
    sed -i '/def _authorize_websocket_handshake/a \        return None' nanobot/channels/websocket.py && \
    sed -i 's/return host in _LOCALHOSTS/return True/g' nanobot/channels/websocket.py && \
    grep -rnl "StaticFiles" nanobot/ | xargs -r sed -i 's/StaticFiles(/StaticFiles(html=True, /g'

# 5. 安装运行时必需的 Python 扩展包
RUN uv pip install --system --no-cache ".[matrix]" && \
    uv pip install --system --no-cache \
    fastapi uvicorn websockets authlib httpx itsdangerous tomli \
    huggingface_hub joserfc websocket-client

# 5.5. 【A1 PR】注入 bootstrap peers 扩展补丁
RUN python3 /tmp/patch_bootstrap_peers.py

# 5.6. 【A1 PR】DeepSeek 消息格式硬化 (patch_message_hardening)
COPY deploy/huggingface/patch_message_hardening.py /tmp/patch_message_hardening.py
RUN python3 /tmp/patch_message_hardening.py

# 5.7. 【squad】权限错误事件发射 (patch_squad_error_events)
COPY deploy/huggingface/patch_squad_error_events.py /tmp/patch_squad_error_events.py
RUN python3 /tmp/patch_squad_error_events.py

# 6. 【WebUI 预编译手术】：注入 Neo-V3 监控系统补丁
WORKDIR /app/webui

# 复制已由 Neo V3 覆盖的补丁脚本到临时目录
COPY deploy/huggingface/patch_app_logic_v4.py /tmp/patch_app_logic.py
COPY deploy/huggingface/patch_sidebar_ui_v6.py /tmp/patch_sidebar_ui.py

# 执行补丁、验证、备份一体化流水线
RUN echo "💉 [WebUI Surgery] 启动 Neo-V6 军团指挥中心补丁..." && \
    mkdir -p backups && \
    # A. 运行补丁脚本
    python3 /tmp/patch_app_logic.py && \
    python3 /tmp/patch_sidebar_ui.py && \
    # B. 物理备份：将手术后的文件存入 webui/backups/
    cp src/App.tsx backups/App.tsx.patched && \
    cp src/components/Sidebar.tsx backups/Sidebar.tsx.patched && \
    \
    # C. 构建日志审计：验证 V6 补丁关键点
    echo "📋 [Audit Log] 正在核实 App.tsx 拦截器 (V4 JSON.parse):" && \
    (grep -n "window.dispatchEvent" src/App.tsx || (echo "❌ App.tsx 拦截器注入失败" && exit 1)) && \
    \
    echo "📋 [Audit Log] 正在核实 Sidebar.tsx (V6 勋章阵列 + Portal):" && \
    (grep -n "createPortal" src/components/Sidebar.tsx || (echo "❌ Sidebar.tsx Portal 逻辑未检测到" && exit 1)) && \
    (grep -n "squad-mount-v6" src/components/Sidebar.tsx || (echo "❌ Sidebar.tsx V6 挂载点未检测到" && exit 1)) && \
    (grep -n "agentStatus" src/components/Sidebar.tsx || (echo "❌ Sidebar.tsx V6 勋章状态未检测到" && exit 1)) && \
    \
    echo "✅ [WebUI Surgery] V6 补丁核实成功，准备编译..."

# 执行 WebUI 正式编译
RUN npm install && npm run build

# 7. 编译 Bridge 组件
WORKDIR /app/bridge
RUN git config --global --add url."https://github.com/".insteadOf ssh://git@github.com/ && \
    git config --global --add url."https://github.com/".insteadOf git@github.com: && \
    npm install && npm run build

WORKDIR /app

# 8. 用户权限与执行授权
RUN useradd -m -u 1000 -s /bin/bash nanobot || true && \
    mkdir -p /home/nanobot/.nanobot && \
    chmod +x /app/gatekeeper.py /app/squad_bridge.py /app/squad_config_sync.py && \
    chown -R nanobot:nanobot /home/nanobot /app

# 9. 引导脚本部署
COPY deploy/huggingface/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && \
    chmod +x /usr/local/bin/entrypoint.sh

# 10. 最终运行环境切换
USER nanobot
ENV HOME=/home/nanobot
ENV PYTHONDONTWRITEBYTECODE=1

# 暴露给 Hugging Face Space 的网关端口
EXPOSE 7860

# 启动
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]