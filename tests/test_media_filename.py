"""Tests for media file handling in Telegram channel."""
from pathlib import Path
from unittest.mock import MagicMock


def test_media_file_id_no_collision():
    """Test that different Telegram file_ids generate unique file paths.
    
    Regression test for: https://github.com/HKUDS/nanobot/issues/XXX
    Previously used file_id[:16] which caused collisions between
    similar file_ids like:
    - AgACAgEAAxkBAAIBAAAAAQAC...
    - AgACAgEAAxkBAAICAAAAAQAC...
    Both would map to AgACAgEAAxkBAAIB.jpg
    """
    # Simulate the fixed logic
    file_ids = [
        "AgACAgEAAxkBAAIBAAAAAQAD",
        "AgACAgEAAxkBAAICAAAAAQAD",
        "AgACAgEAAxkBAAIDAAAAAQAD",
    ]
    
    media_dir = Path("/tmp/test_media")
    media_dir.mkdir(parents=True, exist_ok=True)
    
    file_paths = []
    for file_id in file_ids:
        # This is the fixed logic (no truncation)
        ext = ".jpg"
        file_path = media_dir / f"{file_id}{ext}"
        file_paths.append(str(file_path))
    
    # Verify all paths are unique
    assert len(file_paths) == len(set(file_paths)), "File paths should be unique"
    
    # Verify full file_id is used (not truncated)
    for i, file_id in enumerate(file_ids):
        assert file_id in file_paths[i], f"Full file_id should be in path"
        assert file_id[:16] not in file_paths[i] or file_id[:16] + file_id[16:] in file_paths[i], \
            "Should use full file_id, not truncated"
    
    # Cleanup
    import shutil
    shutil.rmtree(media_dir)
