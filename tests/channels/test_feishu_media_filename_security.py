from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.channels import feishu as feishu_module
from nanobot.channels.feishu import FeishuChannel


@pytest.mark.asyncio
async def test_feishu_downloaded_media_filename_cannot_escape_media_dir(monkeypatch, tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    outside = tmp_path / "escaped.txt"

    monkeypatch.setattr(feishu_module, "get_media_dir", lambda _channel: media_dir)

    channel = FeishuChannel.__new__(FeishuChannel)
    channel.logger = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )

    def fake_download(_message_id, _file_key, _resource_type):
        return b"owned", "../escaped.txt"

    channel._download_file_sync = fake_download

    path_str, content = await channel._download_and_save_media(
        "file", {"file_key": "fk_123"}, "msg_123"
    )

    saved_path = Path(path_str)
    assert not outside.exists()
    assert saved_path.parent == media_dir
    assert saved_path.name == "escaped.txt"
    assert saved_path.read_bytes() == b"owned"
    assert content == f"[file: {saved_path}]"
