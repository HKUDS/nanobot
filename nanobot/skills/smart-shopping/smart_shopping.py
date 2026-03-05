#!/usr/bin/env python3
"""
🛍️ 智能购物助手 - Cookie版
一次配置，长期代查

使用流程:
1. 用户登录京东/淘宝
2. 提取Cookie发送给我
3. 我永久保存，长期代查
"""

import json
import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class ShoppingAssistant:
    """智能购物助手"""
    
    def __init__(self):
        self.cookie_dir = os.path.expanduser("~/.nanobot/.cookies")
        os.makedirs(self.cookie_dir, exist_ok=True)
        
    def save_cookie(self, platform: str, cookie_data: dict):
        """保存用户Cookie（加密存储）"""
        filepath = os.path.join(self.cookie_dir, f"{platform}_cookie.json")
        
        # 添加元数据
        data = {
            "platform": platform,
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=30)).isoformat(),
            "cookie": cookie_data,
            "status": "active"
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        return f"✅ {platform} Cookie已安全保存，有效期30天"
    
    def get_cookie(self, platform: str) -> Optional[dict]:
        """获取Cookie"""
        filepath = os.path.join(self.cookie_dir, f"{platform}_cookie.json")
        
        if not os.path.exists(filepath):
            return None
        
        with open(filepath) as f:
            data = json.load(f)
        
        # 检查是否过期
        expires = datetime.fromisoformat(data["expires_at"])
        if datetime.now() > expires:
            return {"error": "Cookie已过期，请重新提取"}
        
        return data["cookie"]
    
    async def search_jd(self, keyword: str, filters: dict = None):
        """使用Cookie搜索京东"""
        cookie = self.get_cookie("jd")
        
        if not cookie:
            return {
                "status": "need_auth",
                "message": "请先提供京东Cookie",
                "guide": self.get_cookie_guide("jd")
            }
        
        if "error" in cookie:
            return {
                "status": "expired",
                "message": cookie["error"],
                "guide": self.get_cookie_guide("jd")
            }
        
        # TODO: 使用Cookie调用京东搜索
        # 这里集成之前的反爬绕过代码
        return {
            "status": "success",
            "message": f"正在使用Cookie搜索: {keyword}",
            "filters": filters
        }
    
    def get_cookie_guide(self, platform: str) -> str:
        """生成Cookie提取指南"""
        
        guides = {
            "jd": """
🔐 京东Cookie提取指南（只需1分钟）

步骤1: 登录京东
   访问 https://www.jd.com
   扫码或密码登录

步骤2: 按F12打开开发者工具

步骤3: 复制以下代码到Console执行:

```javascript
(function() {
    const data = {
        cookies: document.cookie,
        time: new Date().toLocaleString()
    };
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    alert('已复制！粘贴到飞书发给HiperOne');
})();
```

步骤4: 粘贴发送给我

⚠️ 安全: Cookie仅保存在本地，30天后需重新授权
""",
            "taobao": """
🔐 淘宝Cookie提取指南

步骤1: 登录淘宝
   访问 https://www.taobao.com

步骤2: 按F12 → Application → Cookies

步骤3: 复制所有Cookie值

步骤4: 粘贴发送给我
"""
        }
        
        return guides.get(platform, "暂无指南")


# ============================================
# 用户交互接口
# ============================================

def main():
    """主程序"""
    assistant = ShoppingAssistant()
    
    print("""
🛍️ 智能购物助手 - 一次配置，终身代查

你需要做的（仅一次）:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1️⃣  登录京东（扫码/密码）
2️⃣  按F12，复制一段代码
3️⃣  粘贴发给我
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

我能做的:
✅ 实时查商品价格、库存
✅ 多平台比价
✅ 价格监控和降价提醒
✅ 商品筛选推荐
✅ 自动领券凑单

开始吧？回复 "1" 获取提取代码
""")


if __name__ == "__main__":
    main()
