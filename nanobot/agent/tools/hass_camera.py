"""Tool to fetch camera snapshots from Home Assistant."""

from typing import Any
import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.utils.helpers import build_image_content_blocks

class HassCameraSnapshotTool(Tool):
    """Fetches a camera snapshot from Home Assistant."""
    
    def __init__(self, ha_url: str, ha_token: str):
        self.ha_url = ha_url.rstrip('/')
        self.ha_token = ha_token
        # Remove trailing /api/mcp if present
        if self.ha_url.endswith("/api/mcp"):
            self.ha_url = self.ha_url[:-8]

    @property
    def name(self) -> str:
        return "hass_camera_snapshot"

    @property
    def description(self) -> str:
        return "Get a visual snapshot from a Home Assistant camera (e.g., to see what is happening in a room)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The exact Home Assistant entity ID of the camera (e.g., 'camera.kitchen', 'camera.balcony_camera', 'camera.livingroom_camera'). If unsure, common names are camera.kitchen, camera.balcony, camera.livingroom_camera."
                }
            },
            "required": ["entity_id"]
        }

    async def execute(self, entity_id: str, **kwargs: Any) -> Any:
        if not entity_id.startswith("camera."):
            entity_id = f"camera.{entity_id}"

        url = f"{self.ha_url}/api/camera_proxy/{entity_id}"
        headers = {
            "Authorization": f"Bearer {self.ha_token}"
        }

        logger.info("[HassCameraSnapshotTool] Requesting snapshot for entity: {}", entity_id)

        try:
            # 10 second timeout to prevent hanging the loop if camera is too slow
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
                
                if response.status_code == 200:
                    raw_data = response.content
                    mime = response.headers.get("Content-Type", "image/jpeg")
                    logger.success("[HassCameraSnapshotTool] Snapshot fetched successfully ({} bytes)", len(raw_data))
                    # Build multimodal image format expected by LLM
                    return build_image_content_blocks(
                        raw=raw_data,
                        mime=mime,
                        path=entity_id,
                        label=f"(Snapshot from {entity_id})"
                    )
                else:
                    err_msg = f"Error: Could not fetch snapshot for {entity_id}. Status: {response.status_code}. Response: {response.text[:200]}"
                    logger.error("[HassCameraSnapshotTool] Failed: {}", err_msg)
                    return err_msg
        except httpx.TimeoutException:
            logger.error("[HassCameraSnapshotTool] Timeout fetching snapshot for {}", entity_id)
            return f"Error: Timeout while waiting for snapshot from {entity_id}."
        except Exception as e:
            logger.exception("[HassCameraSnapshotTool] Exception fetching snapshot")
            return f"Error fetching snapshot: {str(e)}"
