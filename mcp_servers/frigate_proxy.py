import asyncio
import base64
import json
import os
import threading
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Frigate Cameras")

HA_URL = os.environ.get("HA_URL", "http://192.168.22.111:8123")
HA_TOKEN = os.environ.get(
    "HA_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJkODNkOTQ1NWMyNzg0MWFjYmJiNGYxZmRkNDQ5NGZiNiIsImlhdCI6MTc3NjM3OTY3MiwiZXhwIjoyMDkxNzM5NjcyfQ.sRTGRUD8UhTLdVnc--9nsqBrJ0nN1v8EzaS8OitKOuE",
)
SNAPSHOT_DIR = Path("/tmp/camera_snapshots")
SNAPSHOT_PORT = 18999
DOCKER_HOST_IP = os.environ.get("DOCKER_HOST_IP", "192.168.22.102")


def _headers():
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


@mcp.tool()
async def list_cameras() -> str:
    cameras = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{HA_URL}/api/states", headers=_headers())
            for e in resp.json():
                if e["entity_id"].startswith("camera."):
                    name = e["entity_id"].replace("camera.", "").replace("_", " ").title()
                    cameras.append({"entity_id": e["entity_id"], "state": e["state"], "name": name})
    except Exception as e:
        return json.dumps({"error": str(e)})
    return json.dumps(cameras, indent=2, ensure_ascii=False)


@mcp.tool()
async def camera_snapshot(camera_entity: str) -> str:
    """Take a snapshot from a camera entity and return it as base64 data URL + file path.

    Use the returned data_url to read the image directly — no need for read_file.

    Args:
        camera_entity: e.g. camera.livingroom_camera, camera.corridor_camera, camera.kitchen, camera.pantry
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    file_path = SNAPSHOT_DIR / f"{camera_entity.replace('.', '_')}.jpg"
    thumb_name = f"thumb_{camera_entity.replace('.', '_')}.png"
    http_url = f"http://{DOCKER_HOST_IP}:{SNAPSHOT_PORT}/{thumb_name}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{HA_URL}/api/camera_proxy/{camera_entity}", headers=_headers())
            resp.raise_for_status()
            file_path.write_bytes(resp.content)

        data = resp.content

        thumb_path = SNAPSHOT_DIR / thumb_name
        try:
            from PIL import Image
            img = Image.open(file_path).convert("RGB")
            img.thumbnail((240, 240), Image.LANCZOS)
            img.save(thumb_path, "PNG")
            thumb_data = thumb_path.read_bytes()
        except Exception:
            thumb_path.write_bytes(data)
            thumb_data = data

        b64 = base64.b64encode(data).decode()
        data_url = f"data:image/jpeg;base64,{b64}"
        thumb_b64 = base64.b64encode(thumb_data).decode()
        thumb_data_url = f"data:image/png;base64,{thumb_b64}"

        return json.dumps({
            "success": True,
            "file_path": str(file_path),
            "http_url": http_url,
            "data_url": data_url,
            "thumbnail_data_url": thumb_data_url,
            "size_bytes": len(data),
            "hint": (
                "The image is in data_url above — you can see it directly here. "
                f"The http_url ({http_url}) is a 240x240 PNG thumbnail for ESP32 screen. "
                "To show on the Xiaozhi speaker screen, use call_xiaozhi_tool with "
                'self.screen.preview_image and pass the http_url.'
            ),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to get snapshot from {camera_entity}: {e}"})


@mcp.tool()
async def frigate_events(camera_name: str | None = None) -> str:
    """Get recent Frigate events/detections (person, car, etc.)

    Args:
        camera_name: optional filter (e.g. corridor, livingroom, kitchen, balcony)
    """
    try:
        frigate_url = os.environ.get("FRIGATE_URL", "http://192.168.22.111:5000")
        params = {"limit": 10}
        if camera_name:
            params["camera"] = camera_name
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{frigate_url}/api/events", params=params)
            events = resp.json()
            summary = []
            for e in events[:10]:
                summary.append({
                    "label": e.get("label"),
                    "camera": e.get("camera"),
                    "start_time": e.get("start_time"),
                    "has_snapshot": e.get("has_snapshot"),
                    "has_clip": e.get("has_clip"),
                })
            return json.dumps(summary, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Failed to get Frigate events: {e}"})


def _start_http_server():
    """Serve snapshots via HTTP so Xiaozhi ESP32 can fetch them."""
    import http.server

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(SNAPSHOT_DIR), **kwargs)

        def log_message(self, fmt, *args):
            pass

    server = http.server.HTTPServer(("0.0.0.0", SNAPSHOT_PORT), Handler)
    server.serve_forever()


threading.Thread(target=_start_http_server, daemon=True).start()

if __name__ == "__main__":
    mcp.run(transport="stdio")
