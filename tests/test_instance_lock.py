from pathlib import Path
from nanobot.config.instance_lock import (
    confirm_single_instance,
    cleanup_lock,
    _get_lock_file_path
)


def test_lock_file_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    lock_file = _get_lock_file_path(config_path)
    assert lock_file == tmp_path / ".config.json.lock"


def test_lock_mechanism_single_process(tmp_path: Path) -> None:
    config_path = tmp_path / "test_config.json"
    config_path.touch()
    
    try:
        result1 = confirm_single_instance(config_path)
        assert result1 is True
        assert _get_lock_file_path(config_path).exists()
        
        result2 = confirm_single_instance(config_path)
        assert result2 is False
        
        cleanup_lock()
        assert not _get_lock_file_path(config_path).exists()
        
        result3 = confirm_single_instance(config_path)
        assert result3 is True
        
    finally:
        cleanup_lock()


def test_cleanup_nonexistent_lock() -> None:
    cleanup_lock()
    assert True


def test_lock_with_nonexistent_config_dir(tmp_path: Path) -> None:
    deep_path = tmp_path / "non" / "existent" / "dir" / "config.json"
    
    result = confirm_single_instance(deep_path)
    assert result is True
    assert _get_lock_file_path(deep_path).exists()
    
    cleanup_lock()
    assert not _get_lock_file_path(deep_path).exists()
