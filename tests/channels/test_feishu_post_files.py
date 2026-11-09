from __future__ import annotations

import json

from nanobot.channels.feishu import runtime as feishu_runtime

# Payloads captured from a real p2p chat (file keys replaced with
# placeholders). Sending text + a file together makes the Feishu client
# deliver ONE post message whose attachments live in a top-level "files"
# array; before this was handled the attachment was silently dropped.
_POST_WITH_FILE = json.loads(
    '{"title": "",'
    ' "content": [[{"tag": "text", "text": "see attached", "style": []}]],'
    ' "content_v2": [[{"tag": "text", "text": "see attached", "style": []}]],'
    ' "files": [{"file_key": "file_v3_00175_key",'
    '             "file_name": "notice.pdf", "is_folder": false}]}'
)

_POST_WITH_FOLDER = json.loads(
    '{"title": "",'
    ' "content": [[{"tag": "text", "text": "my project", "style": []}]],'
    ' "files": [{"file_key": "file_v3_0116t_key",'
    '             "file_name": "first-flask", "is_folder": true}]}'
)

_POST_LOCALIZED = {
    "zh_cn": {
        "title": "",
        "content": [[{"tag": "text", "text": "附件"}]],
        "files": [
            {"file_key": "file_localized", "file_name": "成绩.pdf", "is_folder": False}
        ],
    }
}

_POST_WRAPPED = {
    "post": {
        "zh_cn": {
            "title": "",
            "content": [[{"tag": "text", "text": "wrapped"}]],
            "files": [
                {"file_key": "file_wrapped", "file_name": "a.txt", "is_folder": False}
            ],
        }
    }
}

_POST_WITHOUT_FILES = {
    "title": "",
    "content": [[{"tag": "text", "text": "plain text only"}]],
}


def test_extracts_file_from_direct_post_payload() -> None:
    files, folders = feishu_runtime._extract_post_attachments(_POST_WITH_FILE)
    assert folders == []
    assert len(files) == 1
    assert files[0]["file_key"] == "file_v3_00175_key"
    assert files[0]["file_name"] == "notice.pdf"


def test_folder_is_reported_for_graceful_fallback_not_download() -> None:
    files, folders = feishu_runtime._extract_post_attachments(_POST_WITH_FOLDER)
    assert files == []
    assert folders == ["first-flask"]


def test_extracts_files_from_localized_payload() -> None:
    files, folders = feishu_runtime._extract_post_attachments(_POST_LOCALIZED)
    assert folders == []
    assert [f["file_key"] for f in files] == ["file_localized"]


def test_extracts_files_from_post_envelope_payload() -> None:
    files, folders = feishu_runtime._extract_post_attachments(_POST_WRAPPED)
    assert folders == []
    assert [f["file_key"] for f in files] == ["file_wrapped"]


def test_returns_empty_when_payload_has_no_files() -> None:
    assert feishu_runtime._extract_post_attachments(_POST_WITHOUT_FILES) == ([], [])
    assert feishu_runtime._extract_post_attachments({}) == ([], [])


def test_skips_entries_without_usable_file_key() -> None:
    payload = {
        "content": [],
        "files": [
            {"file_name": "no-key.pdf", "is_folder": False},
            {"file_key": "", "is_folder": False},
            "not-a-dict",
            {"file_key": "file_ok", "file_name": "ok.pdf", "is_folder": False},
        ],
    }
    files, folders = feishu_runtime._extract_post_attachments(payload)
    assert folders == []
    assert [f["file_key"] for f in files] == ["file_ok"]


def test_folder_without_name_gets_placeholder() -> None:
    payload = {"content": [], "files": [{"file_key": "file_f", "is_folder": True}]}
    _, folders = feishu_runtime._extract_post_attachments(payload)
    assert folders == ["folder"]


def test_caption_still_extracted_alongside_files() -> None:
    """Regression guard: attachment handling must not break text/images."""
    text, images = feishu_runtime._extract_post_content(_POST_WITH_FILE)
    assert text == "see attached"
    assert images == []
