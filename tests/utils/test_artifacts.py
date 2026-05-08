from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nanobot.config.loader import set_config_path
from nanobot.utils.artifacts import (
    ArtifactError,
    decode_image_data_url,
    generated_image_paths_from_messages,
    generated_image_tool_result,
    store_generated_image_artifact,
)

PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def test_decode_image_data_url_validates_image_payload() -> None:
    raw, mime = decode_image_data_url(PNG_DATA_URL)

    assert raw.startswith(b"\x89PNG")
    assert mime == "image/png"

    with pytest.raises(ArtifactError):
        decode_image_data_url("data:image/png;base64,not-base64")


def test_store_generated_image_artifact_writes_image_and_sidecar(tmp_path: Path) -> None:
    set_config_path(tmp_path / "config.json")
    created_at = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

    artifact = store_generated_image_artifact(
        PNG_DATA_URL,
        prompt="draw a tiny pixel",
        model="openai/gpt-5.4-image-2",
        source_images=["/tmp/ref.png"],
        save_dir="generated",
        created_at=created_at,
    )

    image_path = Path(artifact["path"])
    assert image_path.is_file()
    assert image_path.parent == tmp_path / "media" / "generated" / "2026-05-08"
    assert artifact["id"].startswith("img_")
    assert artifact["mime"] == "image/png"

    sidecar = image_path.with_suffix(".json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    assert metadata["path"] == str(image_path)
    assert metadata["source_images"] == ["/tmp/ref.png"]


def test_store_generated_image_artifact_rejects_unsafe_save_dir(tmp_path: Path) -> None:
    set_config_path(tmp_path / "config.json")

    with pytest.raises(ArtifactError):
        store_generated_image_artifact(
            PNG_DATA_URL,
            prompt="x",
            model="m",
            save_dir="../outside",
        )


def test_generated_image_paths_from_tool_results() -> None:
    result = generated_image_tool_result(
        [
            {"id": "img_1", "path": "/tmp/one.png"},
            {"id": "img_2", "path": "/tmp/two.png"},
        ]
    )

    assert generated_image_paths_from_messages(
        [
            {"role": "tool", "name": "generate_image", "content": result},
            {"role": "tool", "name": "other", "content": result},
        ]
    ) == ["/tmp/one.png", "/tmp/two.png"]
