#!/bin/bash
# 构建 Docker 镜像 (WSL/Linux)

set -e

echo "=== 构建 Nanobot Agent 镜像 ==="
cd "$(dirname "$0")"
cd ..

docker build -f shared/Dockerfile.agent -t nanobot-agent:latest .

echo "=== 镜像构建完成 ==="
docker images | grep nanobot
