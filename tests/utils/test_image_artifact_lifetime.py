from pathlib import Path

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.hooks.image_artifacts import ImageArtifactsHook
from nanobot.bus.notification_delivery import notification_is_deliverable
from nanobot.events import EventSink
from nanobot.providers.base import ToolCallRequest
from nanobot.utils.artifacts import (
    ArtifactError,
    decode_image_data_url,
    store_generated_image_artifact,
)
from nanobot.utils.image_artifacts import (
    EphemeralImageStore,
    ImageArtifact,
    ImageArtifactResult,
    ImageArtifactsEvent,
)

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="


def test_ephemeral_image_lifetime_has_no_sidecars_and_cannot_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.utils.artifacts.get_media_dir", lambda: tmp_path)
    store = EphemeralImageStore()
    artifact = store_generated_image_artifact(
        PNG, prompt="synthetic prompt", model="fixture", ephemeral_store=store,
    )
    path = Path(artifact["path"])
    assert path.exists()
    assert not path.with_suffix(".json").exists()
    assert "prompt" not in artifact
    assert not list(tmp_path.iterdir())
    assert store.attachment(str(path))["url"] == PNG
    assert EphemeralImageStore().attachment(str(path)) is None
    exported = tmp_path / "user-export.png"
    exported.write_bytes(path.read_bytes())
    store.close()
    store.close()
    assert not path.exists()
    assert exported.exists()
    assert store.attachment(str(path)) is None
    with pytest.raises(ArtifactError, match="closed"):
        store_generated_image_artifact(PNG, prompt="x", model="x", ephemeral_store=store)


def test_image_limits_fail_before_storage():
    with pytest.raises(ArtifactError, match="32 MiB"):
        decode_image_data_url("data:image/png;base64," + "A" * (44 * 1024 * 1024))
    store = EphemeralImageStore()
    with pytest.raises(ValueError, match="limit"):
        store.store("img_fixture", b"x" * (4 * 1024 * 1024 + 1), "image/png", ".png")
    store.close()


def test_model_history_copy_strips_runtime_artifact_references():
    from copy import deepcopy

    original = ImageArtifactResult("compact observation", (ImageArtifact("id", "/image.png", "image/png", "fixture"),))
    copied = deepcopy(original)
    assert type(copied) is str
    assert copied == "compact observation"


async def test_only_typed_deliverables_emit_bounded_deduplicated_events():
    events = []

    async def publish(event):
        events.append(event)

    hook = ImageArtifactsHook(EventSink(publish))
    context = AgentHookContext(iteration=1, messages=[])
    call = ToolCallRequest(id="image-call", name="fixture", arguments={})
    images = tuple(ImageArtifact(str(i), f"/fixture/{i}.png", "image/png", "fixture")
                   for i in range(40))
    await hook.after_execute_tool(context, call, None, {}, '{"artifacts":[{"path":"/secret.png"}]}')
    await hook.after_execute_tool(context, call, None, {}, ImageArtifactResult("observed", ()))
    assert not events
    await hook.after_execute_tool(context, call, None, {}, ImageArtifactResult("done", images))
    await hook.after_execute_tool(context, call, None, {}, ImageArtifactResult("duplicate", images))
    assert len(events) == 1
    assert events[0].tool_call_id == "image-call"
    assert len(events[0].artifacts) == 32
    for channel in ("telegram", "slack", "cli"):
        assert not notification_is_deliverable(ImageArtifactsEvent, channel=channel, publish_lifecycle=True)
    assert notification_is_deliverable(ImageArtifactsEvent, channel="websocket", publish_lifecycle=False)


async def test_temporary_images_can_be_explicitly_sent_but_other_chat_images_cannot(tmp_path):
    from unittest.mock import AsyncMock

    from nanobot.agent.tools.context import RequestContext, request_context
    from nanobot.agent.tools.message import MessageTool

    own, other = EphemeralImageStore(), EphemeralImageStore()
    images = [store_generated_image_artifact(PNG, prompt="fixture", model="fixture", ephemeral_store=s)
              for s in (own, other)]
    send = AsyncMock()
    tool = MessageTool(send_callback=send, workspace=tmp_path, restrict_to_workspace=True)
    try:
        with request_context(RequestContext(channel="websocket", chat_id="fixture", ephemeral_images=own)):
            result = await tool.execute(content="Requested screenshot", media=[images[0]["path"]])
            assert not getattr(result, "is_error", False)
            assert send.await_count == 1
            await tool.execute(content="Other screenshot", media=[images[1]["path"]])
            assert send.await_count == 1
    finally:
        own.close()
        other.close()
