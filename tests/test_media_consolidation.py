from nanobot.agent.memory import MemoryStore
from nanobot.session.manager import Session

PATH = "/root/.nanobot/media/websocket/upload_photo.png"
msg = {"role": "user", "content": "", "media": [PATH], "timestamp": "2026-07-27T10:00"}

# 实时回放（应该保留路径）
replay = Session(key="demo", messages=[msg]).get_history()[0]["content"]
print("replay :", repr(replay))

# 归档格式化（现在应该也保留路径）
print("archive:", repr(MemoryStore._format_messages([msg])))