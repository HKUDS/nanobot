#!/usr/bin/env python3
"""Quick test script for Nanobot BFF - validates imports and basic structure."""

import sys
from pathlib import Path

# Add parent to path for nanobot imports
sys.path.insert(0, str(Path(__file__).parent.parent))

print("=" * 60)
print("Nanobot BFF - 快速验证测试")
print("=" * 60)

# Test 1: Config imports
print("\n[1/5] 测试配置模块...")
try:
    from config import DATABASE_PATH, DATA_DIR, DEFAULT_MODEL
    print(f"  ✅ 配置加载成功")
    print(f"     数据库路径: {DATABASE_PATH}")
    print(f"     默认模型: {DEFAULT_MODEL}")
except Exception as e:
    print(f"  ❌ 配置加载失败: {e}")
    sys.exit(1)

# Test 2: Models imports
print("\n[2/5] 测试数据模型...")
try:
    from models import (
        ConversationCreate,
        ConversationResponse,
        MessageSend,
        MessageResponse,
        TrajectoryTuple,
        HealthResponse,
    )
    print(f"  ✅ 数据模型加载成功")
except Exception as e:
    print(f"  ❌ 数据模型加载失败: {e}")
    sys.exit(1)

# Test 3: Database initialization
print("\n[3/5] 测试数据库初始化...")
try:
    import asyncio
    from database import Database

    async def test_db():
        db = Database(":memory:")
        await db.init()
        conv_id = await db.create_conversation("测试对话", "deepseek-chat")
        print(f"  ✅ 数据库初始化成功")
        print(f"     创建测试对话 ID: {conv_id}")
        return conv_id

    conv_id = asyncio.run(test_db())
except Exception as e:
    print(f"  ❌ 数据库初始化失败: {e}")
    sys.exit(1)

# Test 4: Pydantic models validation
print("\n[4/5] 测试数据验证...")
try:
    conv = ConversationCreate(title="测试", model="deepseek-chat")
    msg = MessageSend(conversation_id=conv_id, content="你好")
    traj = TrajectoryTuple(
        turn_id=1,
        state={"test": "data"},
        action="用户动作",
        observation="Agent回复",
        reward=1.0
    )
    print(f"  ✅ 数据验证通过")
except Exception as e:
    print(f"  ❌ 数据验证失败: {e}")
    sys.exit(1)

# Test 5: FastAPI app import
print("\n[5/5] 测试 FastAPI 应用...")
try:
    from main import app
    print(f"  ✅ FastAPI 应用加载成功")
    print(f"     路由数量: {len(app.routes)}")
except Exception as e:
    print(f"  ❌ FastAPI 应用加载失败: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ 所有验证测试通过!")
print("=" * 60)
print("\n启动方式:")
print("  cd nanobot_bff")
print("  python main.py")
print("\n然后打开浏览器访问:")
print("  http://localhost:8000/frontend/index.html")
print("=" * 60)
