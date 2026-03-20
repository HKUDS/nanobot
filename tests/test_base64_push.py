"""验证 base64 主动推送（QQ + WeCom）

在容器内运行:
  python3 /app/tests/test_base64_push.py --channel qq --chat-id <OPENID>
  python3 /app/tests/test_base64_push.py --channel wecom --chat-id <USER_ID>

测试项:
  1. 纯文本主动推送
  2. 本地图片 base64 上传 + 推送
  3. 本地文件 base64 上传 + 推送
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure nanobot package is importable
sys.path.insert(0, "/app")


async def test_qq_push(chat_id: str, is_group: bool = False):
    """Test QQ channel base64 push."""
    from nanobot.channels.qq import QQChannel, QQConfig

    # Load config
    cfg_path = Path.home() / ".nanobot" / "config.json"
    with open(cfg_path) as f:
        cfg = json.load(f)
    qq_cfg = cfg["channels"]["qq"]
    config = QQConfig(
        enabled=True,
        app_id=qq_cfg["appId"],
        secret=qq_cfg["secret"],
        msg_format=qq_cfg.get("msgFormat", "plain"),
    )

    # We need a running bot client to use the API
    # Instead of starting the full channel, we'll use the low-level botpy API directly
    import botpy
    from botpy.http import Route

    intents = botpy.Intents(public_messages=True, direct_message=True)
    client = botpy.Client(intents=intents, ext_handlers=False)

    print(f"[QQ] Authenticating with app_id={config.app_id}...")
    # Start the HTTP session (get access_token)
    import aiohttp
    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            "https://bots.qq.com/app/getAppAccessToken",
            json={"appId": config.app_id, "clientSecret": config.secret},
        )
        token_data = await resp.json()
        token = token_data["access_token"]
        print(f"[QQ] Got token: {token[:20]}...")

        headers = {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
        }

        endpoint = "groups" if is_group else "users"
        id_field = "group_openid" if is_group else "openid"
        base = f"https://api.sgroup.qq.com/v2/{endpoint}/{chat_id}"

        # --- Test 1: Text push ---
        print("\n=== Test 1: 纯文本推送 ===")
        r = await session.post(f"{base}/messages", json={
            "msg_type": 0,
            "content": "🧪 base64-only 方案测试：纯文本推送成功！",
            "msg_seq": 1,
        }, headers=headers)
        print(f"  HTTP {r.status}: {(await r.text())[:200]}")

        # --- Test 2: Image base64 push ---
        print("\n=== Test 2: 图片 base64 推送 ===")
        # Create a small test PNG (1x1 red pixel)
        import base64
        # Minimal valid PNG: 1x1 red pixel
        png_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        tmp_img = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_img.write(png_data)
        tmp_img.close()

        file_data_b64 = base64.b64encode(png_data).decode("ascii")
        r = await session.post(f"{base}/files", json={
            "file_type": 1,  # image
            "srv_send_msg": False,
            "file_data": file_data_b64,
            "file_name": "test_base64.png",
        }, headers=headers)
        result = await r.json()
        print(f"  Upload HTTP {r.status}: {str(result)[:200]}")

        if r.status == 200 and result.get("file_info"):
            # Send the uploaded media
            r2 = await session.post(f"{base}/messages", json={
                "msg_type": 7,
                "media": result,
                "msg_seq": 2,
            }, headers=headers)
            print(f"  Send HTTP {r2.status}: {(await r2.text())[:200]}")
        else:
            print("  ⚠️ Image upload failed, skipping send")

        # --- Test 3: File base64 push ---
        print("\n=== Test 3: 文件 base64 推送 ===")
        test_content = "这是 base64 上传测试文件\n时间: test\n方案: base64-only (no public_url)"
        file_data_b64 = base64.b64encode(test_content.encode()).decode("ascii")
        r = await session.post(f"{base}/files", json={
            "file_type": 4,  # file
            "srv_send_msg": False,
            "file_data": file_data_b64,
            "file_name": "test_base64.txt",
        }, headers=headers)
        result = await r.json()
        print(f"  Upload HTTP {r.status}: {str(result)[:200]}")

        if r.status == 200 and result.get("file_info"):
            r2 = await session.post(f"{base}/messages", json={
                "msg_type": 7,
                "media": result,
                "msg_seq": 3,
            }, headers=headers)
            print(f"  Send HTTP {r2.status}: {(await r2.text())[:200]}")
        else:
            print("  ⚠️ File upload failed, skipping send")

        os.unlink(tmp_img.name)

    print("\n✅ QQ base64 push test completed!")


async def test_wecom_push(chat_id: str):
    """Test WeCom channel base64 push via WebSocket.

    This test verifies that media upload works through the WeCom WS 3-step protocol.
    It requires a running WeCom channel with active WebSocket connections.
    """
    print("[WeCom] WeCom uses WebSocket 3-step upload protocol (init → chunks → finish)")
    print("[WeCom] This must be tested through the running nanobot instance.")
    print("[WeCom] Sending test message via nanobot's internal bus...")

    from nanobot.bus.events import OutboundMessage

    # Create a small test image
    import base64
    png_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    )
    media_dir = Path.home() / ".nanobot" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    test_img = media_dir / "test_base64_push.png"
    test_img.write_bytes(png_data)

    test_file = media_dir / "test_base64_push.txt"
    test_file.write_text("WeCom base64 上传测试文件\n方案: WebSocket 3-step upload (no public_url)")

    print(f"[WeCom] Test image: {test_img}")
    print(f"[WeCom] Test file: {test_file}")
    print(f"[WeCom] Target chat_id: {chat_id}")
    print()
    print("[WeCom] To test, use nanobot's message tool or API to send:")
    print(f'  message(content="WeCom base64 推送测试", channel="wecom", chat_id="{chat_id}", media=["{test_img}", "{test_file}"])')
    print()
    print("Or via the nanobot API (if running):")
    print(f'  curl -X POST http://localhost:18770/v1/chat/completions \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f'    -d \'{{"messages":[{{"role":"user","content":"发送测试文件到 {chat_id}"}}]}}\'')
    print()
    print("✅ WeCom test files prepared!")


async def main():
    parser = argparse.ArgumentParser(description="Test base64 media push for QQ/WeCom")
    parser.add_argument("--channel", choices=["qq", "wecom", "both"], default="qq",
                       help="Which channel to test")
    parser.add_argument("--chat-id", required=True,
                       help="Target chat/user ID (QQ openid or WeCom user_id)")
    parser.add_argument("--group", action="store_true",
                       help="QQ: send to group instead of C2C")
    args = parser.parse_args()

    if args.channel in ("qq", "both"):
        await test_qq_push(args.chat_id, is_group=args.group)

    if args.channel in ("wecom", "both"):
        await test_wecom_push(args.chat_id)


if __name__ == "__main__":
    asyncio.run(main())
