"""Test WeCom base64 push via nanobot internal message bus.

Run in container:
  python3 /app/tests/test_wecom_push.py
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")


async def test_wecom_send():
    # Prepare test files
    media_dir = Path("/tmp/test_media")
    media_dir.mkdir(parents=True, exist_ok=True)

    # 1x1 red PNG
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    )
    test_img = media_dir / "test_wecom.png"
    test_img.write_bytes(png_data)

    test_file = media_dir / "test_wecom.txt"
    test_file.write_text("WeCom base64 upload test\nScheme: WebSocket 3-step (no public_url)")

    from nanobot.bus.events import OutboundMessage
    from nanobot.bus.queue import MessageBus

    with open("/root/.nanobot/config.json") as f:
        cfg = json.load(f)

    bots = cfg["channels"]["wecom"].get("bots", [])
    print(f"WeCom bots: {len(bots)}")

    chat_id = "T05860039A"
    bot_id = bots[1]["botId"] if len(bots) > 1 else bots[0]["botId"]
    session_key = f"wecom:{bot_id}:{chat_id}"
    print(f"Target: {session_key}")

    bus = MessageBus()

    # Test 1: Text message
    print("\n=== Test 1: WeCom 纯文本推送 ===")
    msg1 = OutboundMessage(
        channel="wecom",
        chat_id=chat_id,
        content="🧪 WeCom base64-only 方案测试：纯文本推送！",
        metadata={"session_key": session_key, "bot_id": bot_id},
    )
    await bus.publish_outbound(msg1)
    print("  Published text message to bus")
    await asyncio.sleep(2)

    # Test 2: Image
    print("\n=== Test 2: WeCom 图片推送 ===")
    msg2 = OutboundMessage(
        channel="wecom",
        chat_id=chat_id,
        content="🧪 WeCom base64 图片推送测试",
        media=[str(test_img)],
        metadata={"session_key": session_key, "bot_id": bot_id},
    )
    await bus.publish_outbound(msg2)
    print("  Published image message to bus")
    await asyncio.sleep(3)

    # Test 3: File
    print("\n=== Test 3: WeCom 文件推送 ===")
    msg3 = OutboundMessage(
        channel="wecom",
        chat_id=chat_id,
        content="🧪 WeCom base64 文件推送测试",
        media=[str(test_file)],
        metadata={"session_key": session_key, "bot_id": bot_id},
    )
    await bus.publish_outbound(msg3)
    print("  Published file message to bus")
    await asyncio.sleep(3)

    print("\n✅ WeCom test messages published!")


if __name__ == "__main__":
    asyncio.run(test_wecom_send())
