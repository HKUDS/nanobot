from nanobot.agent.memory import MemoryStore
from nanobot.session.manager import Session

PATH = "/root/.nanobot/media/websocket/upload_photo.png"
MSG = {"role": "user", "content": "", "media": [PATH], "timestamp": "2026-07-27T10:00"}


def test_media_consolidation_preserves_path():
    """Test that media path is preserved in both replay and archive."""
    # Replay (live session)
    replay_content = Session(key="demo", messages=[MSG]).get_history()[0]["content"]
    assert "[image: /root/.nanobot/media/websocket/upload_photo.png]" in replay_content

    # Archive (consolidation)
    archive_formatted = MemoryStore._format_messages([MSG])
    assert "[image: /root/.nanobot/media/websocket/upload_photo.png]" in archive_formatted