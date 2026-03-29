from nanobot.config.schema import MemoryIndexConfig


def test_memory_index_config_defaults_include_injection_fields():
    cfg = MemoryIndexConfig()
    assert cfg.inject_top_k == 3
    assert cfg.watch_files is True


def test_memory_index_config_inject_top_k_can_be_zero():
    cfg = MemoryIndexConfig(inject_top_k=0)
    assert cfg.inject_top_k == 0


def test_memory_index_config_watch_files_can_be_disabled():
    cfg = MemoryIndexConfig(watch_files=False)
    assert cfg.watch_files is False


async def test_index_service_start_indexes_memory_file(tmp_path):
    from nanobot.memory_index.service import IndexService

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("## Facts\n\nUser likes Python programming.\n")

    cfg = MemoryIndexConfig()
    cfg.watch_files = False  # disable watcher — not tested here
    service = IndexService(tmp_path, cfg)
    await service.start()

    results = await service.index.search("Python programming", top_k=1)
    assert len(results) >= 1
    assert "Python" in results[0].text

    await service.stop()


async def test_index_service_stop_is_idempotent(tmp_path):
    from nanobot.memory_index.service import IndexService

    cfg = MemoryIndexConfig()
    cfg.watch_files = False
    service = IndexService(tmp_path, cfg)
    await service.start()
    await service.stop()
    await service.stop()  # must not raise


async def test_index_service_stop_without_start_is_safe(tmp_path):
    from nanobot.memory_index.service import IndexService

    cfg = MemoryIndexConfig()
    cfg.watch_files = False
    service = IndexService(tmp_path, cfg)
    await service.stop()  # must not raise — observer is None
