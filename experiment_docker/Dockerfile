FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制整个项目（包括 pyproject.toml）
COPY . /app

# 安装 nanobot 依赖（使用根目录的 pyproject.toml）
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -e /app

# 额外安装实验依赖
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple docker

# 创建必要的目录结构
RUN mkdir -p /app/personal/logs /app/personal/results /root/.nanobot/workspaces

# 设置环境变量支持
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV NANOBOT_WORKSPACE=/root/.nanobot/workspaces

WORKDIR /app/experiment_docker

ENTRYPOINT ["python"]
CMD ["run_llm_comparison.py"]
