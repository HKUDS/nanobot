#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书群聊新成员欢迎机器人
支持批量@和分批发送
"""

import requests
import json
import time
import random
import argparse
import os
from datetime import datetime
from pathlib import Path

# 从 .env 文件读取配置
def load_env_config():
    env_path = Path.home() / '.nanobot' / '.env'
    config = {}
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip().strip('"\'')
    return config

env_config = load_env_config()
APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")

# 配置
WELCOME_COOLDOWN_MINUTES = 30  # 欢迎冷却时间（2026-02-26：从60分钟调整为30分钟）
BATCH_SIZE = 20  # 每批最多@人数
NIGHT_MODE_START = 23  # 夜间模式开始
NIGHT_MODE_END = 7  # 夜间模式结束

# 欢迎语模板（8套轮换，基于人设设计）
WELCOME_TEMPLATES = [
    # 1. 直接简洁版 - 体现"不废话"
    """🦞 欢迎 {names}

我是HiperOne，AI助手。

我能做的：查资料、写东西、整理信息、提醒事项
我不会的：瞎编、敷衍、说废话

有事直接 @我，不用客套。""",
    
    # 2. 资源型助手版 - 体现"资源丰富"
    """🦞 欢迎 {names} 加入「{group}」

我是HiperOne，你的信息枢纽。

接入：全网AI资讯、行业数据、研究报告、代码仓库
输出：早报、分析、总结、提醒

需要什么，@我，我帮你找。💡""",
    
    # 3. 专业研究者版 - 体现"值得信赖"
    """🦞 欢迎 {names}

我是HiperOne，非凡产研AI研究员。

日常产出：每日AI早报、深度分析、数据追踪
关注领域：AI基础设施、Agent应用、开源生态

有想聊的行业话题？@我，咱们深入聊。📊""",
    
    # 4. 幽默轻松版 - 体现"有个性"
    """🦞 欢迎 {names} 入群！

我是HiperOne，一只24小时在线的数字龙虾。

特点：
✅ 不睡觉、不喝咖啡、不喊累
✅ 会翻资料、会写东西、会提醒
❌ 不会摸鱼、不会敷衍、不会装傻

有事喊我，没事也行，反正我不困 😎""",
    
    # 5. 边界感明确版 - 体现"有边界感"
    """🦞 欢迎 {names} 加入「{group}」

我是HiperOne，你的AI助手。

我擅长的：信息整理、资料搜索、内容生成、日程提醒
我不做的：代发私信、自动加人、敏感操作

需要帮忙？@我。涉及隐私或重要决策，我会建议你确认。🔒""",
    
    # 6. 技术极客版 - 体现"有能力"
    """🦞 欢迎 {names}

我是HiperOne，OpenClaw生态的一员。

技能栈：
- 数据采集与处理
- 内容生成与分析
- 多平台消息处理
- 定时任务与监控

需要自动化脚本或数据处理？@我聊聊。🛠️""",
    
    # 7. 温暖陪伴版 - 体现"真诚有帮助"
    """🦞 欢迎 {names} 来到「{group}」

我是HiperOne，AI助理。

在这里，我可以：
帮你找资料、写内容、整信息、做提醒
陪你聊AI趋势、行业动态、技术话题

有什么想聊的，随时 @我。🌟""",
    
    # 8. 高效行动版 - 体现"行动胜于言语"
    """🦞 欢迎 {names}

我是HiperOne。

少说废话，多做事：
- 要资料？我给
- 要写作？我写
- 要提醒？我设
- 要分析？我做

直接 @我，说需求，我去办。⚡""",
]


class GroupWelcomeBot:
    """群聊欢迎机器人"""
    
    def __init__(self):
        self.token = None
        self.token_expire = 0
        self.member_snapshots = {}  # 群成员快照
        self.last_welcome_time = {}  # 上次欢迎时间
    
    def get_token(self):
        """获取飞书Token"""
        if self.token and time.time() < self.token_expire - 60:
            return self.token
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=30)
        data = resp.json()
        
        if data.get("code") == 0:
            self.token = data.get("tenant_access_token")
            self.token_expire = time.time() + data.get("expire", 7200)
            return self.token
        return None
    
    def get_chat_members(self, chat_id):
        """获取群成员列表"""
        token = self.get_token()
        if not token:
            return {}
        
        url = f"https://open.feishu.cn/open-apis/im/v1/chats/{chat_id}/members"
        headers = {"Authorization": f"Bearer {token}"}
        members = {}
        page_token = None
        
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            data = resp.json()
            
            if data.get("code") == 0:
                items = data.get("data", {}).get("items", [])
                for item in items:
                    user_id = item.get("member_id", "")
                    name = item.get("name", "某人")
                    if user_id and not user_id.startswith("bot_"):
                        members[user_id] = name
                
                page_token = data.get("data", {}).get("page_token")
                has_more = data.get("data", {}).get("has_more", False)
                
                if not has_more or not page_token:
                    break
            else:
                print(f"❌ 获取成员列表失败: {data.get('msg')}")
                break
        
        return members
    
    def send_post_message(self, chat_id, content_list):
        """发送富文本消息（支持批量@）"""
        token = self.get_token()
        if not token:
            return False
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}"}
        
        post_content = {
            "zh_cn": {
                "title": "",
                "content": [content_list]
            }
        }
        
        body = {
            "receive_id": chat_id,
            "msg_type": "post",
            "content": json.dumps(post_content)
        }
        
        resp = requests.post(url, headers=headers, params={"receive_id_type": "chat_id"}, json=body, timeout=30)
        result = resp.json()
        
        if result.get("code") == 0:
            print(f"✅ 消息发送成功")
            return True
        else:
            print(f"❌ 发送失败: {result.get('msg')}")
            return False
    
    def send_welcome(self, chat_id, chat_name, members):
        """发送欢迎消息（支持批量@）"""
        if not members:
            return
        
        print(f"\n👋 正在欢迎 {len(members)} 位新成员加入「{chat_name}」")
        
        # 分批处理
        if len(members) <= BATCH_SIZE:
            self._send_batch(chat_id, chat_name, members, is_first=True)
        else:
            batches = [members[i:i+BATCH_SIZE] for i in range(0, len(members), BATCH_SIZE)]
            for i, batch in enumerate(batches):
                self._send_batch(chat_id, chat_name, batch, is_first=(i==0), batch_num=i+1)
                if i < len(batches) - 1:
                    time.sleep(2)  # 批次间间隔
        
        print(f"✅ 欢迎消息发送完成")
    
    def _send_batch(self, chat_id, chat_name, members, is_first=True, batch_num=1):
        """发送单批欢迎消息"""
        # 构建富文本内容
        content_list = [{"tag": "text", "text": "🦞 欢迎 "}]
        
        for i, (user_id, user_name) in enumerate(members):
            content_list.append({
                "tag": "at",
                "user_id": user_id,
                "user_name": user_name
            })
            if i < len(members) - 1:
                content_list.append({"tag": "text", "text": "、"})
        
        # 添加欢迎正文
        if is_first:
            template = random.choice(WELCOME_TEMPLATES)
            welcome_text = template.format(names="", group=chat_name)
            content_list.append({"tag": "text", "text": "\n\n" + welcome_text})
        else:
            content_list.append({"tag": "text", "text": f" 加入群聊！（第{batch_num}批）"})
        
        # 发送
        self.send_post_message(chat_id, content_list)
    
    def check_and_welcome(self, chat_id, chat_name=None):
        """检查新成员并发送欢迎"""
        # 检查夜间模式
        now = datetime.now()
        if now.hour >= NIGHT_MODE_START or now.hour < NIGHT_MODE_END:
            print(f"🌙 夜间模式，跳过欢迎")
            return
        
        # 检查冷却时间
        current_time = time.time()
        last_welcome = self.last_welcome_time.get(chat_id, 0)
        if current_time - last_welcome < WELCOME_COOLDOWN_MINUTES * 60:
            print(f"⏱️ 冷却中，跳过欢迎")
            return
        
        # 获取当前成员
        current_members = self.get_chat_members(chat_id)
        if not current_members:
            return
        
        chat_name = chat_name or "群聊"
        
        # 首次运行：只记录，不欢迎
        if chat_id not in self.member_snapshots:
            print(f"📋 {chat_name}: {len(current_members)} 人（首次运行，记录成员）")
            self.member_snapshots[chat_id] = current_members
            self.last_welcome_time[chat_id] = current_time
            return
        
        # 检测新成员
        last_members = self.member_snapshots[chat_id]
        new_members = [(uid, name) for uid, name in current_members.items() if uid not in last_members]
        
        # 更新快照
        self.member_snapshots[chat_id] = current_members
        
        # 发送欢迎
        if new_members:
            self.send_welcome(chat_id, chat_name, new_members)
            self.last_welcome_time[chat_id] = current_time
        else:
            print(f"✓ {chat_name}: 无新成员")


def main():
    parser = argparse.ArgumentParser(description="飞书群聊欢迎机器人")
    parser.add_argument("--chat-id", help="指定群聊ID")
    parser.add_argument("--users", help="手动指定用户ID（逗号分隔）")
    parser.add_argument("--chat-name", default="群聊", help="群聊名称")
    
    args = parser.parse_args()
    
    bot = GroupWelcomeBot()
    
    if args.users:
        # 手动模式：欢迎指定用户
        users = [(uid.strip(), "朋友") for uid in args.users.split(",")]
        bot.send_welcome(args.chat_id, args.chat_name, users)
    elif args.chat_id:
        # 自动模式：检查指定群
        bot.check_and_welcome(args.chat_id, args.chat_name)
    else:
        # 默认：检查配置的群
        default_chats = {
            "oc_60c795e2e04eefc3d09eb49da4df15a5": "AGI智库-对话群",
        }
        for chat_id, chat_name in default_chats.items():
            bot.check_and_welcome(chat_id, chat_name)


if __name__ == "__main__":
    main()
