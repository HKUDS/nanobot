"""Inbound attachment names must not cause another attachment to be overwritten."""

from email.message import EmailMessage

import pytest

from nanobot.channels.email.runtime import EmailChannel


@pytest.mark.parametrize(
    "filenames",
    [
        ("report.txt", "report.txt"),
        ("report:2026.txt", "report?2026.txt"),
        ("report.txt", "report.txt", "report_1.txt"),
    ],
)
def test_extract_attachments_preserves_colliding_filenames(tmp_path, monkeypatch, filenames):
    monkeypatch.setattr("nanobot.channels.email.runtime.get_media_dir", lambda _channel: tmp_path)
    message = EmailMessage()
    message.set_content("Both reports are attached.")
    contents = [f"report {index}".encode() for index in range(len(filenames))]
    for filename, content in zip(filenames, contents):
        message.add_attachment(content, maintype="text", subtype="plain", filename=filename)

    paths = EmailChannel._extract_attachments(
        message, "500", allowed_types=["text/plain"], max_size=100, max_count=len(filenames),
    )

    assert len(paths) == len(set(paths)) == len(filenames)
    assert [path.read_bytes() for path in paths] == contents
