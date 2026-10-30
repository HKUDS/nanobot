import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, get_ident

import pytest
import tiktoken.load
from loguru import logger

from nanobot.utils import helpers, token_encoding


@pytest.fixture(autouse=True)
def isolate_warmup(monkeypatch, tmp_path, byte_encoding):
    monkeypatch.setattr(token_encoding, "_warmup_thread", None)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(token_encoding.tiktoken, "get_encoding", lambda _name: byte_encoding)
    yield
    worker = token_encoding._warmup_thread
    if worker is not None and worker.ident is not None:
        worker.join(timeout=5)
        assert not worker.is_alive()


def finish_warmup():
    worker = token_encoding._warmup_thread
    assert worker is not None
    worker.join(timeout=5)
    assert not worker.is_alive()


def test_slow_warmup_does_not_block_concurrent_estimates(monkeypatch, byte_encoding):
    entered, release = Event(), Event()
    calls = []
    caller_thread = get_ident()

    def load(name):
        calls.append((name, get_ident()))
        entered.set()
        assert release.wait(5)
        return byte_encoding

    monkeypatch.setattr(token_encoding.tiktoken, "get_encoding", load)
    token_encoding.warmup_token_encoding()
    try:
        assert entered.wait(2)
        with ThreadPoolExecutor(max_workers=8) as pool:
            pending = [pool.submit(helpers.estimate_message_tokens, {"content": "🙂你"}) for _ in range(37)]
            assert [task.result(timeout=1) for task in pending] == [11] * 37
        assert helpers.estimate_prompt_tokens_chain(object(), "test", [{"content": "hello"}]) == (9, "heuristic")
        assert len(helpers.truncate_text_to_tokens("hello " * 100, 40).encode()) <= 40
        assert len(calls) == 1 and calls[0][0] == "cl100k_base"
        assert calls[0][1] != caller_thread
    finally:
        release.set()
        finish_warmup()
    assert token_encoding.get_token_encoding() is byte_encoding
    assert helpers.estimate_prompt_tokens_chain(object(), "test", [{"content": "hello"}]) == (9, "tiktoken")


def test_direct_consumer_starts_warmup_without_waiting(monkeypatch, byte_encoding):
    release = Event()

    def load(_name):
        assert release.wait(5)
        return byte_encoding

    monkeypatch.setattr(token_encoding.tiktoken, "get_encoding", load)
    try:
        assert token_encoding.get_token_encoding() is None
        assert token_encoding._warmup_thread is not None
    finally:
        release.set()
        finish_warmup()
    assert token_encoding.get_token_encoding() is byte_encoding


def test_failed_warmup_is_not_retried_per_message(monkeypatch):
    calls, warnings = [], []

    def fail(_name):
        calls.append(_name)
        raise OSError("offline")

    monkeypatch.setattr(token_encoding.tiktoken, "get_encoding", fail)
    sink = logger.add(lambda message: warnings.append(str(message)), level="WARNING")
    try:
        token_encoding.warmup_token_encoding()
        finish_warmup()
        for _ in range(37):
            token_encoding.warmup_token_encoding()
            assert helpers.estimate_prompt_tokens_chain(object(), "test", [{"content": "hi"}]) == (6, "heuristic")
        assert calls == ["cl100k_base"]
        assert len(warnings) == 1 and "until restart" in warnings[0]
    finally:
        logger.remove(sink)


@pytest.mark.parametrize("variable,value", [
    (None, None), ("TIKTOKEN_CACHE_DIR", "custom-cache"),
    ("DATA_GYM_CACHE_DIR", "legacy-cache"), ("TIKTOKEN_CACHE_DIR", ""),
])
def test_cache_location_respects_configuration(monkeypatch, tmp_path, variable, value):
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    if variable:
        monkeypatch.setenv(variable, value)
    token_encoding.warmup_token_encoding()
    finish_warmup()
    if variable:
        assert os.environ[variable] == value
        if variable == "DATA_GYM_CACHE_DIR":
            assert "TIKTOKEN_CACHE_DIR" not in os.environ
    else:
        assert os.environ["TIKTOKEN_CACHE_DIR"] == str(tmp_path / "cache" / "tiktoken")


def test_completed_download_is_reused_after_reinitialization(monkeypatch, byte_encoding):
    downloads = []
    payload = b"test vocabulary"
    checksum = hashlib.sha256(payload).hexdigest()

    def download(url):
        downloads.append(url)
        return payload

    def load(_name):
        assert tiktoken.load.read_file_cached("https://example.test/vocabulary", checksum) == payload
        return byte_encoding

    monkeypatch.setattr(tiktoken.load, "read_file", download)
    monkeypatch.setattr(token_encoding.tiktoken, "get_encoding", load)
    for _ in range(2):
        monkeypatch.setattr(token_encoding, "_warmup_thread", None)
        monkeypatch.setattr(token_encoding, "_encoding", None)
        token_encoding.warmup_token_encoding()
        finish_warmup()
        assert token_encoding.get_token_encoding() is byte_encoding
    assert downloads == ["https://example.test/vocabulary"]


def test_stalled_download_does_not_hold_up_process_exit(tmp_path):
    code = """
from threading import Event
from nanobot.utils import token_encoding
from nanobot.utils.helpers import estimate_message_tokens
started = Event()
def blocked(_name):
    started.set()
    Event().wait()
token_encoding.tiktoken.get_encoding = blocked
token_encoding.warmup_token_encoding()
assert started.wait(2)
assert estimate_message_tokens({"content": "hello"}) == 9
print("chat completed; exiting with download pending")
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "TIKTOKEN_CACHE_DIR": str(tmp_path)},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "chat completed; exiting with download pending" in result.stdout
