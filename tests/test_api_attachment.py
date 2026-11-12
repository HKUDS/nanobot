from __future__ import annotations

import base64
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from nanobot.api.server import (
    _FileSizeExceeded,
    _parse_json_content,
    _save_base64_data_url,
    create_app,
)

try:
    from aiohttp.test_utils import TestClient, TestServer

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

pytest_plugins = ("pytest_asyncio",)

API_KEY = "secret"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def _make_mock_agent(response_text: str = "mock response") -> MagicMock:
    agent = MagicMock()
    agent.process_direct = AsyncMock(return_value=response_text)
    agent.aclose = AsyncMock()
    return agent


@pytest.fixture
def mock_agent():
    return _make_mock_agent()


@pytest_asyncio.fixture
async def aiohttp_client():
    clients: list[TestClient] = []

    async def _make_client(app):
        client = TestClient(TestServer(app))
        await client.start_server()
        clients.append(client)
        return client

    try:
        yield _make_client
    finally:
        for client in clients:
            await client.close()


def test_save_base64_data_url_saves_png(tmp_path) -> None:
    b64_data = base64.b64encode(b"fake png data").decode()
    data_url = f"data:image/png;base64,{b64_data}"
    result = _save_base64_data_url(data_url, tmp_path)
    assert result is not None
    assert result.endswith(".png")
    assert (tmp_path / result.replace(str(tmp_path) + "/", "")).read_bytes() == b"fake png data"


def test_save_base64_data_url_handles_invalid_b64(tmp_path) -> None:
    result = _save_base64_data_url("data:image/png;base64,not-valid-base64!!!", tmp_path)
    assert result is None


def test_save_base64_data_url_handles_unknown_mime(tmp_path) -> None:
    b64_data = base64.b64encode(b"some data").decode()
    data_url = f"data:unknown/type;base64,{b64_data}"
    result = _save_base64_data_url(data_url, tmp_path)
    assert result is not None
    assert result.endswith(".bin")


def test_save_base64_data_url_rejects_oversized_payload(tmp_path) -> None:
    large_payload = base64.b64encode(b"x" * (11 * 1024 * 1024)).decode()
    data_url = f"data:image/png;base64,{large_payload}"

    with pytest.raises(_FileSizeExceeded, match="10MB limit"):
        _save_base64_data_url(data_url, tmp_path)


def test_parse_json_content_extracts_text_and_media(tmp_path) -> None:
    b64_data = base64.b64encode(b"img").decode()
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe this"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_data}"}},
                ],
            }
        ]
    }
    import os
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        text, media_paths = _parse_json_content(body)
        assert text == "describe this"
        assert len(media_paths) == 1
    finally:
        os.chdir(original_cwd)


def test_parse_json_content_rejects_malformed_parameter_header_without_stalling(tmp_path) -> None:
    # Isolate the parser so a backtracking regression cannot hang the test runner.
    code = """
import sys
from pathlib import Path
from unittest.mock import patch

from nanobot.api.server import _parse_json_content

media_dir = Path(sys.argv[1])
url = "data:image/png" + ";a" * 128 + ",eA=="
body = {"messages": [{"role": "user", "content": [
    {"type": "text", "text": "describe this"},
    {"type": "image_url", "image_url": {"url": url}},
]}]}
with patch("nanobot.api.server.get_media_dir", return_value=media_dir):
    assert _parse_json_content(body) == ("describe this", [])
assert list(media_dir.iterdir()) == []
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_parse_json_content_plain_text_only() -> None:
    body = {"messages": [{"role": "user", "content": "hello"}]}
    text, media_paths = _parse_json_content(body)
    assert text == "hello"
    assert media_paths == []


def test_parse_json_content_validates_single_message() -> None:
    body = {
        "messages": [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ]
    }
    with pytest.raises(ValueError, match="single user message"):
        _parse_json_content(body)


def test_parse_json_content_validates_user_role() -> None:
    body = {"messages": [{"role": "system", "content": "you are a bot"}]}
    with pytest.raises(ValueError, match="single user message"):
        _parse_json_content(body)


@pytest.mark.parametrize(
    ("part", "field"),
    [
        ({"type": "text", "text": 1}, r"content\[\]\.text"),
        (
            {"type": "image_url", "image_url": "not-an-object"},
            r"content\[\]\.image_url",
        ),
        (
            {"type": "image_url", "image_url": {"url": 1}},
            r"image_url\.url",
        ),
    ],
)
def test_parse_json_content_validates_typed_block_fields(part, field) -> None:
    body = {"messages": [{"role": "user", "content": [part]}]}

    with pytest.raises(TypeError, match=field):
        _parse_json_content(body)


def test_parse_json_content_rejects_oversized_base64_file(tmp_path) -> None:
    large_payload = base64.b64encode(b"x" * (11 * 1024 * 1024)).decode()
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{large_payload}"}},
                ],
            }
        ]
    }
    import os
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        with pytest.raises(_FileSizeExceeded, match="10MB limit"):
            _parse_json_content(body)
    finally:
        os.chdir(original_cwd)


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_multipart_upload_saves_file(aiohttp_client, mock_agent, tmp_path) -> None:
    import os
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        app = create_app(mock_agent, model_name="m", api_key=API_KEY)
        client = await aiohttp_client(app)

        file_data = b"test file content"
        data = BytesIO(file_data)

        resp = await client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            data={"message": "analyze this", "files": data},
        )
        assert resp.status == 200
        call_kwargs = mock_agent.process_direct.call_args.kwargs
        assert call_kwargs["content"] == "analyze this"
        assert len(call_kwargs.get("media") or []) == 1
    finally:
        os.chdir(original_cwd)


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_multipart_multiple_files(aiohttp_client, mock_agent, tmp_path, monkeypatch) -> None:
    import aiohttp

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    monkeypatch.setattr("nanobot.api.server.get_media_dir", lambda _channel=None: media_dir)
    app = create_app(mock_agent, model_name="m", api_key=API_KEY)
    client = await aiohttp_client(app)

    files = [("first.txt", b"first file content"), ("second.bin", b"\x00second file\xff")]
    data = aiohttp.FormData()
    data.add_field("message", "analyze both files")
    for filename, payload in files:
        data.add_field("files", payload, filename=filename, content_type="application/octet-stream")

    resp = await client.post("/v1/chat/completions", headers=AUTH_HEADERS, data=data)

    assert resp.status == 200
    mock_agent.process_direct.assert_called_once()
    mock_agent.process_direct.assert_awaited_once()
    call_kwargs = mock_agent.process_direct.call_args.kwargs
    assert call_kwargs["content"] == "analyze both files"
    saved_paths = [Path(path) for path in call_kwargs["media"]]
    assert len(saved_paths) == 2
    assert saved_paths[0] != saved_paths[1]
    for path, (_, payload) in zip(saved_paths, files, strict=True):
        assert path.parent == media_dir
        assert path.read_bytes() == payload


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_multipart_file_size_limit(aiohttp_client, mock_agent, tmp_path) -> None:
    import os
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        app = create_app(mock_agent, model_name="m", api_key=API_KEY)
        client = await aiohttp_client(app)

        large_data = b"x" * (11 * 1024 * 1024)
        data = BytesIO(large_data)

        resp = await client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            data={"message": "analyze", "files": data},
        )
        assert resp.status == 413
    finally:
        os.chdir(original_cwd)


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_multipart_defaults_text_when_missing(aiohttp_client, mock_agent, tmp_path) -> None:
    import os
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        app = create_app(mock_agent, model_name="m", api_key=API_KEY)
        client = await aiohttp_client(app)

        file_data = b"content"
        data = BytesIO(file_data)

        resp = await client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            data={"files": data},
        )
        assert resp.status == 200
        call_kwargs = mock_agent.process_direct.call_args.kwargs
        assert call_kwargs["content"] == "请分析上传的文件"
    finally:
        os.chdir(original_cwd)


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
@pytest.mark.parametrize(("session_id", "chat_id"), [
    ("my-session", "my-session"), (" my-session ", "my-session"), ("  ", "default"),
])
async def test_multipart_with_session_id(
    aiohttp_client, mock_agent, tmp_path, session_id, chat_id,
) -> None:
    import os
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        app = create_app(mock_agent, model_name="m", api_key=API_KEY)
        client = await aiohttp_client(app)

        file_data = b"content"
        data = BytesIO(file_data)

        resp = await client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            data={"message": "hello", "session_id": session_id, "files": data},
        )
        assert resp.status == 200
        call_kwargs = mock_agent.process_direct.call_args.kwargs
        assert call_kwargs["session_key"] == f"api:{chat_id}"
        assert call_kwargs["chat_id"] == chat_id
    finally:
        os.chdir(original_cwd)


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_plain_text_backward_compat(aiohttp_client, mock_agent) -> None:
    app = create_app(mock_agent, model_name="m", api_key=API_KEY)
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        headers=AUTH_HEADERS,
        json={"messages": [{"role": "user", "content": "hello world"}]},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == "mock response"
    call_kwargs = mock_agent.process_direct.call_args.kwargs
    assert call_kwargs["content"] == "hello world"
    assert call_kwargs.get("media") is None


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
@pytest.mark.parametrize("marker", ["base64", "BASE64", "Base64"])
async def test_json_base64_image_upload(
    aiohttp_client, mock_agent, tmp_path, monkeypatch, marker: str,
) -> None:
    monkeypatch.setattr("nanobot.api.server.get_media_dir", lambda _channel=None: tmp_path)
    app = create_app(mock_agent, model_name="m", api_key=API_KEY)
    client = await aiohttp_client(app)

    tiny_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="

    resp = await client.post(
        "/v1/chat/completions",
        headers=AUTH_HEADERS,
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;{marker},{tiny_png_b64}"}},
                    ],
                }
            ]
        },
    )
    assert resp.status == 200
    mock_agent.process_direct.assert_awaited_once()
    call_kwargs = mock_agent.process_direct.call_args.kwargs
    assert call_kwargs["content"] == "what is this"
    saved, = call_kwargs["media"]
    assert Path(saved).parent == tmp_path
    assert Path(saved).read_bytes() == base64.b64decode(tiny_png_b64)


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_docx_upload_passes_media_path(aiohttp_client, tmp_path) -> None:
    agent = _make_mock_agent("report summary")
    import os
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    try:
        app = create_app(agent, model_name="m", api_key=API_KEY)
        client = await aiohttp_client(app)

        from docx import Document
        doc = Document()
        doc.add_paragraph("Total revenue: $5,000,000")
        buf = BytesIO()
        doc.save(buf)

        import aiohttp
        data = aiohttp.FormData()
        data.add_field("message", "summarize the report")
        data.add_field("files", buf.getvalue(), filename="report.docx",
                       content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

        resp = await client.post("/v1/chat/completions", headers=AUTH_HEADERS, data=data)
        assert resp.status == 200
        call_kwargs = agent.process_direct.call_args.kwargs
        assert call_kwargs["content"] == "summarize the report"
        media = call_kwargs.get("media", [])
        assert len(media) == 1
        assert "report.docx" in media[0]
    finally:
        os.chdir(original_cwd)
