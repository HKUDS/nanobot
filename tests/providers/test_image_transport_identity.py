from __future__ import annotations

import base64
import io
from copy import deepcopy
from hashlib import sha256

import pytest
from PIL import Image, PngImagePlugin

from nanobot.providers.base import LLMResponse, ProviderConversationState
from nanobot.providers.images import (
    image_input_ids,
    image_inputs_available,
    prepare_inline_images,
    preserve_image_input_ids,
    state_image_input_ids,
)
from nanobot.providers.openai_responses.state import attach_responses_state


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("url", ["https://images.example.com/prepared.png", "data:image/png;base64,c21hbGw="])
async def test_small_and_remote_image_replay_strips_private_metadata_without_mutation(native, url):
    identifier = sha256(b"original image URL").hexdigest()
    block = {
        "type": "input_image" if native else "image_url",
        "image_url": url if native else {"url": url},
        "_meta": {"image_input_id": identifier, "path": "private-original.png"},
    }
    body = {"input" if native else "messages": [{"role": "user", "content": [block]}]}
    before = deepcopy(body)

    prepared = await prepare_inline_images(body)

    assert image_input_ids(body) == (identifier,)
    assert image_input_ids(prepared) == (sha256(url.encode()).hexdigest(),)
    sent_block = prepared["input" if native else "messages"][0]["content"][0]
    assert sent_block == {key: value for key, value in block.items() if key != "_meta"}
    assert body == before


async def test_compaction_keeps_last_logical_ids_when_encodings_and_duplicates_collide():
    urls = []
    with Image.new("RGBA", (520, 520), (20, 60, 100, 80)) as image:
        for label in ("first", "second"):
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("source", label)
            output = io.BytesIO()
            image.save(output, "PNG", compress_level=0, pnginfo=metadata)
            urls.append(f"data:image/png;base64,{base64.b64encode(output.getvalue()).decode()}")
    source = {"input": [
        {"type": "message", "role": "user", "content": [{"type": "input_image", "image_url": url}]}
        for url in (urls[0], urls[1], urls[0])
    ]}
    original_ids = image_input_ids(source)
    sent = await prepare_inline_images(source)
    sent_urls = [item["content"][0]["image_url"] for item in sent["input"]]
    assert len(set(sent_urls)) == 1  # PNG metadata is discarded by real re-encoding.
    assert original_ids[0] == original_ids[2] != original_ids[1]

    result = LLMResponse("compacted")
    attach_responses_state(
        result, provider="fixture", model="fixture", input_items=sent["input"],
        output_items=[{"type": "compaction", "encrypted_content": "opaque"}, *sent["input"][1:]],
    )
    preserve_image_input_ids(result, source, sent)

    assert result.provider_state is not None
    assert state_image_input_ids(result.provider_state) == original_ids[1:]
    assert image_inputs_available(original_ids[1:], [], result.provider_state)
    assert not image_inputs_available(original_ids, [], result.provider_state)
    for item, identifier in zip(result.provider_state.payload["items"][1:], original_ids[1:], strict=True):
        assert item["content"] == [{
            "type": "input_image", "image_url": sent_urls[0],
            "_meta": {"image_input_id": identifier},
        }]
    restored = ProviderConversationState.from_private_record(result.provider_state.to_private_record())
    assert state_image_input_ids(restored) == original_ids[1:]
    assert image_input_ids(sent) != original_ids
    assert image_input_ids(source) == original_ids
