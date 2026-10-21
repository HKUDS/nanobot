"""Cross-suite test infrastructure."""

from __future__ import annotations

import os
import ssl
import sys
from collections.abc import Iterator
from pathlib import Path
from threading import Thread
from uuid import uuid4

import certifi
import pytest
from loguru import logger


@pytest.fixture(autouse=True)
def _isolate_tokenizer_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests deterministic and out of the user's tokenizer cache and network."""
    monkeypatch.setattr("nanobot.utils.token_encoding._encoding", None)
    monkeypatch.setattr("nanobot.utils.token_encoding._warmup_thread", Thread())


@pytest.fixture(autouse=True)
def _isolate_tool_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only load external tool plugins explicitly provided by the test."""
    monkeypatch.setattr("nanobot.agent.tools.loader.entry_points", lambda **_kwargs: ())


@pytest.fixture(autouse=True)
def _isolate_nanobot_log_activation() -> Iterator[None]:
    """Keep CLI log settings from leaking into later tests in the same process."""
    logger.enable("nanobot")
    try:
        yield
    finally:
        logger.enable("nanobot")


@pytest.fixture(autouse=True)
def _isolate_runtime_stores(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate writable stores without making a directory for pure tests."""
    import nanobot.llm_usage.service as llm_usage
    import nanobot.pairing.store as pairing_store
    import nanobot.session.location as session_location
    from nanobot.webui import star_prompt

    # A sibling of tmp_path stays outside any test's agent workspace. mkdir is
    # deferred until a store is used and remains safe for concurrent callers.
    data_root = tmp_path_factory.getbasetemp() / "runtime-data" / uuid4().hex

    def data_dir() -> Path:
        data_root.mkdir(parents=True, exist_ok=True)
        return data_root

    def runtime_subdir(name: str) -> Path:
        path = data_root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr(session_location, "get_runtime_subdir", runtime_subdir)
    monkeypatch.setattr(star_prompt, "get_webui_dir", lambda: runtime_subdir("webui"))
    monkeypatch.setattr(pairing_store, "_store_path", lambda: data_dir() / "pairing.json")
    monkeypatch.setattr(llm_usage, "get_data_dir", data_dir)
    stores: dict[Path, llm_usage.LLMUsageStore] = {}
    monkeypatch.setattr(llm_usage, "_STORES", stores)
    try:
        yield
    finally:
        for store in stores.values():
            store.close()


@pytest.fixture(scope="session", autouse=True)
def _use_windows_system_ca_for_default_http_clients() -> Iterator[None]:
    """Avoid reparsing certifi's CA bundle for every offline HTTP client.

    Loading certifi takes roughly 0.7 seconds per client on Windows. The test
    suite constructs hundreds of clients while mocking their I/O. System roots
    preserve certificate verification for accidental local requests; explicit
    ``cafile``, ``capath``, and ``cadata`` arguments still use the real loader.
    """
    if sys.platform != "win32":
        yield
        return

    original = ssl.create_default_context
    certifi_path = os.path.normcase(os.path.abspath(certifi.where()))

    def create_default_context(
        purpose: ssl.Purpose = ssl.Purpose.SERVER_AUTH,
        *,
        cafile: str | None = None,
        capath: str | None = None,
        cadata: str | bytes | None = None,
    ) -> ssl.SSLContext:
        requested_path = os.path.normcase(os.path.abspath(cafile)) if cafile else None
        if requested_path == certifi_path and capath is None and cadata is None:
            return original(purpose)
        return original(
            purpose,
            cafile=cafile,
            capath=capath,
            cadata=cadata,
        )

    ssl.create_default_context = create_default_context
    try:
        yield
    finally:
        ssl.create_default_context = original


@pytest.fixture
def create_symlink():
    """Create real symlinks, skipping only Windows' missing-privilege error."""
    def create(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except OSError as exc:
            if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
                pytest.skip("Windows symlink creation requires Developer Mode or privilege")
            raise

    return create
