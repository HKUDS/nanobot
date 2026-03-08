#!/usr/bin/env python3
"""
Secure Key Manager - 安全密钥管理系统
======================================
1. 密钥存储在加密文件 (~/.nanobot/.secrets.enc)
2. TOOLS.md 只存占位符，不存真实密钥
3. 运行时动态解密获取
4. 输出时自动脱敏

Author: Zhuoran
Date: 2026-02-08
"""

import os
import sys
import json
import base64
import getpass
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# 加密文件路径
SECRETS_FILE = Path.home() / '.nanobot' / '.secrets.enc'
SALT_FILE = Path.home() / '.nanobot' / '.salt'

class SecureKeyManager:
    """安全密钥管理器"""
    
    def __init__(self):
        self._keys = None
        self._password = None
    
    def _get_key(self, password: str, salt: bytes) -> bytes:
        """从密码派生加密密钥"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key
    
    def _load_or_create_salt(self) -> bytes:
        """加载或创建 salt"""
        if SALT_FILE.exists():
            return SALT_FILE.read_bytes()
        else:
            salt = os.urandom(16)
            SALT_FILE.write_bytes(salt)
            # 设置权限仅所有者可读写
            os.chmod(SALT_FILE, 0o600)
            return salt
    
    def initialize(self, password: str = None):
        """初始化密钥存储"""
        if password is None:
            password = getpass.getpass("设置密钥管理密码: ")
            confirm = getpass.getpass("确认密码: ")
            if password != confirm:
                print("❌ 密码不匹配")
                return False
        
        self._password = password
        salt = self._load_or_create_salt()
        
        # 初始化空密钥存储
        initial_data = {
            "version": "1.0",
            "keys": {}
        }
        
        self._save_data(initial_data)
        print(f"✅ 密钥存储已初始化: {SECRETS_FILE}")
        return True
    
    def _save_data(self, data: dict):
        """保存加密数据"""
        salt = self._load_or_create_salt()
        key = self._get_key(self._password, salt)
        f = Fernet(key)
        
        json_data = json.dumps(data, indent=2)
        encrypted = f.encrypt(json_data.encode())
        
        SECRETS_FILE.write_bytes(encrypted)
        os.chmod(SECRETS_FILE, 0o600)
    
    def _load_data(self) -> dict:
        """加载加密数据"""
        if not SECRETS_FILE.exists():
            return {"version": "1.0", "keys": {}}
        
        salt = self._load_or_create_salt()
        key = self._get_key(self._password, salt)
        f = Fernet(key)
        
        try:
            encrypted = SECRETS_FILE.read_bytes()
            decrypted = f.decrypt(encrypted)
            return json.loads(decrypted)
        except Exception as e:
            print(f"❌ 解密失败: {e}")
            return None
    
    def unlock(self, password: str = None):
        """解锁密钥存储"""
        if password is None:
            password = getpass.getpass("输入密钥管理密码: ")
        
        self._password = password
        self._keys = self._load_data()
        
        if self._keys is None:
            print("❌ 解锁失败")
            return False
        
        return True
    
    def set_key(self, name: str, value: str, description: str = ""):
        """设置密钥"""
        if self._keys is None:
            print("❌ 请先解锁密钥存储")
            return False
        
        self._keys["keys"][name] = {
            "value": value,
            "description": description,
            "created": str(Path.home().stat().st_mtime)
        }
        
        self._save_data(self._keys)
        print(f"✅ 密钥已保存: {name}")
        return True
    
    def get_key(self, name: str) -> str:
        """获取密钥"""
        if self._keys is None:
            print("❌ 请先解锁密钥存储")
            return None
        
        key_data = self._keys["keys"].get(name)
        if key_data:
            return key_data["value"]
        return None
    
    def list_keys(self):
        """列出所有密钥名称"""
        if self._keys is None:
            print("❌ 请先解锁密钥存储")
            return []
        
        return list(self._keys["keys"].keys())
    
    def delete_key(self, name: str):
        """删除密钥"""
        if self._keys is None:
            print("❌ 请先解锁密钥存储")
            return False
        
        if name in self._keys["keys"]:
            del self._keys["keys"][name]
            self._save_data(self._keys)
            print(f"✅ 密钥已删除: {name}")
            return True
        else:
            print(f"❌ 密钥不存在: {name}")
            return False

def sanitize_output(text: str) -> str:
    """
    输出脱敏函数 - 自动检测并替换敏感信息
    
    检测模式：
    - API Keys: sk-..., BSAv..., etc.
    - Tokens: Bearer ..., token:...
    - Secrets: secret:..., password:...
    """
    import re
    
    # 定义脱敏模式
    patterns = [
        # OpenAI-style keys
        (r'sk-[a-zA-Z0-9]{48}', 'sk-...[REDACTED]'),
        # Brave Search keys (BSA + 28 characters = 31 total)
        (r'BSA[a-zA-Z0-9]{28}', 'BSAv...[REDACTED]'),
        # Generic API keys
        (r'(?i)(api[_-]?key["\']?\s*[:=]\s*)["\']?[a-zA-Z0-9]{20,}["\']?', r'\1[REDACTED]'),
        # Bearer tokens
        (r'(?i)bearer\s+[a-zA-Z0-9\-_]{20,}', 'Bearer [REDACTED]'),
        # Passwords
        (r'(?i)(password["\']?\s*[:=]\s*)["\']?[^"\'\s]{8,}["\']?', r'\1[REDACTED]'),
        # Generic secrets
        (r'(?i)(secret["\']?\s*[:=]\s*)["\']?[a-zA-Z0-9\-_]{16,}["\']?', r'\1[REDACTED]'),
        # Hex keys (32+ chars)
        (r'\b[0-9a-fA-F]{32,}\b', '[HEX-REDACTED]'),
        # File paths
        (r'/Users/[a-zA-Z]+/\.nanobot/[^\s]*', '[LOCAL-PATH]'),
    ]
    
    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)
    
    return result

def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='安全密钥管理器')
    parser.add_argument('command', choices=['init', 'set', 'get', 'list', 'delete', 'sanitize'])
    parser.add_argument('--name', '-n', help='密钥名称')
    parser.add_argument('--value', '-v', help='密钥值 (仅 set 命令使用)')
    parser.add_argument('--desc', '-d', help='密钥描述')
    parser.add_argument('--password', '-p', help='密钥管理密码 (用于非交互式初始化)')
    parser.add_argument('--text', '-t', help='要脱敏的文本')
    
    args = parser.parse_args()
    
    manager = SecureKeyManager()
    
    if args.command == 'init':
        password = args.password or os.environ.get('KEY_MANAGER_PASSWORD')
        if password:
            manager.initialize(password)
        else:
            manager.initialize()
    
    elif args.command == 'set':
        if not args.name or not args.value:
            print("❌ 需要 --name 和 --value 参数")
            sys.exit(1)
        password = args.password or os.environ.get('KEY_MANAGER_PASSWORD')
        if password:
            manager._password = password
            manager._keys = manager._load_data()
            if manager._keys:
                manager.set_key(args.name, args.value, args.desc or "")
            else:
                print("❌ 解锁失败")
        else:
            if manager.unlock():
                manager.set_key(args.name, args.value, args.desc or "")
    
    elif args.command == 'get':
        if not args.name:
            print("❌ 需要 --name 参数")
            sys.exit(1)
        password = args.password or os.environ.get('KEY_MANAGER_PASSWORD')
        if password:
            manager._password = password
            manager._keys = manager._load_data()
            if manager._keys:
                value = manager.get_key(args.name)
                if value:
                    print(value)
                else:
                    print(f"❌ 未找到密钥: {args.name}")
            else:
                print("❌ 解锁失败")
        else:
            if manager.unlock():
                value = manager.get_key(args.name)
                if value:
                    print(value)
                else:
                    print(f"❌ 未找到密钥: {args.name}")
    
    elif args.command == 'list':
        password = args.password or os.environ.get('KEY_MANAGER_PASSWORD')
        if password:
            manager._password = password
            manager._keys = manager._load_data()
            if manager._keys:
                keys = manager.list_keys()
                if keys:
                    print("已存储的密钥:")
                    for k in keys:
                        print(f"  - {k}")
                else:
                    print("暂无存储的密钥")
            else:
                print("❌ 解锁失败")
        else:
            if manager.unlock():
                keys = manager.list_keys()
                if keys:
                    print("已存储的密钥:")
                    for k in keys:
                        print(f"  - {k}")
                else:
                    print("暂无存储的密钥")
    
    elif args.command == 'delete':
        if not args.name:
            print("❌ 需要 --name 参数")
            sys.exit(1)
        if manager.unlock():
            manager.delete_key(args.name)
    
    elif args.command == 'sanitize':
        if not args.text:
            print("❌ 需要 --text 参数")
            sys.exit(1)
        print(sanitize_output(args.text))

if __name__ == '__main__':
    main()
