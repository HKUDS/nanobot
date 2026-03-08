---
name: secure-key-manager
description: 安全密钥管理系统，解决 TOOLS.md 中 API Key 明文存储的安全隐患。...
---

# Secure Key Manager - 安全密钥管理技能

## 概述

安全密钥管理系统，解决 TOOLS.md 中 API Key 明文存储的安全隐患。

## 核心功能

1. **加密存储** - AES-256-GCM 加密，密钥派生使用 PBKDF2HMAC
2. **文件权限控制** - 600 权限，仅所有者可访问
3. **运行时动态获取** - 调用时才解密，不常驻内存
4. **输出脱敏** - 自动检测并替换敏感信息，防止意外泄露

## 安装

```bash
# 依赖已包含在系统中
pip3 install cryptography
```

## 使用方法

### 1. 初始化密钥存储

```bash
cd skills/secure-key-manager

# 交互式（推荐）
python3 key_manager.py init

# 非交互式（脚本使用）
python3 key_manager.py init -p "你的密码"
```

### 2. 存储密钥

```bash
# 添加新密钥
python3 key_manager.py set -p "密码" -n "密钥名称" -v "密钥值" -d "描述"

# 示例
python3 key_manager.py set -p "zhuoran2024" \
  -n "brave-search-api-key" \
  -v "BSAviFtiUFyIz2999vFS13X4jlFlXir" \
  -d "Brave Search API Key"
```

### 3. 获取密钥

```bash
python3 key_manager.py get -p "密码" -n "密钥名称"

# 示例
python3 key_manager.py get -p "zhuoran2024" -n "brave-search-api-key"
```

### 4. 列出所有密钥

```bash
python3 key_manager.py list -p "密码"
```

### 5. 输出脱敏

```bash
# 检测并替换文本中的敏感信息
python3 key_manager.py sanitize -t "文本中包含 sk-xxx 等密钥"
```

## 在代码中使用

```python
import sys
sys.path.insert(0, '~/.nanobot/workspace/skills/secure-key-manager')
from key_manager import SecureKeyManager, sanitize_output

# 初始化并解锁
manager = SecureKeyManager()
manager.unlock("密码")

# 获取密钥
api_key = manager.get_key("brave-search-api-key")

# 使用密钥...

# 输出前脱敏
safe_output = sanitize_output("包含密钥的输出文本")
print(safe_output)  # 密钥会被替换为 [REDACTED]
```

## 安全特性

### 1. 多层防护
- 文件系统权限 (0600)
- AES-256-GCM 加密
- PBKDF2HMAC 密钥派生 (48万轮)
- 随机 Salt

### 2. 自动脱敏模式
- `sk-...` - OpenAI 风格 API Key
- `BSA...` - Brave Search Key
- `Bearer ...` - Bearer Token
- `password:...` - 密码
- `secret:...` - Secret
- 32+ 位 Hex 字符串
- 本地文件路径

### 3. 应急响应
一旦发生泄露：
1. 立即撤回消息（无需请示）
2. 轮换相关密钥
3. 更新加密存储
4. 记录安全事件

## 更新记录

- 2026-02-08: 初始版本，支持加密存储、密钥管理和输出脱敏

## 注意事项

1. **密码强度**: 使用强密码，避免简单字符串
2. **备份**: 定期备份 `.secrets.enc` 和 `.salt` 文件
3. **密码遗忘**: 密码遗忘将导致密钥无法恢复，请妥善保管
4. **环境变量**: 可使用 `KEY_MANAGER_PASSWORD` 环境变量避免交互式输入
