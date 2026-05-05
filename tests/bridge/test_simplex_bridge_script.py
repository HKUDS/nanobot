import importlib.util
import json
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[2] / "bridge" / "simplex_bridge.py"
_SPEC = importlib.util.spec_from_file_location("test_simplex_bridge_script_module", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_parse_tail_output_keeps_single_line_messages() -> None:
    stdout = "Alice> Hello\nAlice> Next message\n"

    assert _MODULE._parse_tail_output("Alice", stdout) == [
        (_MODULE._message_token("Alice> Hello"), "Hello"),
        (_MODULE._message_token("Alice> Next message"), "Next message"),
    ]


def test_parse_tail_output_accumulates_multiline_messages() -> None:
    stdout = "Alice> Hello\nWorld\n\nAgain\nAlice> Next message\n"

    assert _MODULE._parse_tail_output("Alice", stdout) == [
        (_MODULE._message_token("Alice> Hello"), "Hello\nWorld\n\nAgain"),
        (_MODULE._message_token("Alice> Next message"), "Next message"),
    ]


def test_parse_tail_output_drops_outbound_echo_boundaries() -> None:
    stdout = "Alice> Hello\nWorld\n@Alice> Reply from bot\nStill outbound\nAlice> Back again\n"

    assert _MODULE._parse_tail_output("Alice", stdout) == [
        (_MODULE._message_token("Alice> Hello"), "Hello\nWorld"),
        (_MODULE._message_token("Alice> Back again"), "Back again"),
    ]


def test_parse_tail_output_handles_timestamped_multiline_messages() -> None:
    stdout = "14:04 Alice> Hello\n14:04 World\n14:05 Alice> Next\n"

    assert _MODULE._parse_tail_output("Alice", stdout) == [
        (_MODULE._message_token("14:04 Alice> Hello"), "Hello\nWorld"),
        (_MODULE._message_token("14:05 Alice> Next"), "Next"),
    ]


def test_load_bridge_state_supports_legacy_format(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"last_seen_token": "tok-1"}), encoding="utf-8")

    assert _MODULE._load_bridge_state(state_path) == ("tok-1", [])


def test_save_bridge_state_keeps_recent_tokens_capped(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    recent_tokens = [f"t-{i}" for i in range(_MODULE._MAX_RECENT_CONTENT_TOKENS + 10)]

    _MODULE._save_bridge_state(state_path, "tok-last", recent_tokens)
    last_seen, loaded_recent = _MODULE._load_bridge_state(state_path)

    assert last_seen == "tok-last"
    assert len(loaded_recent) == _MODULE._MAX_RECENT_CONTENT_TOKENS
    assert loaded_recent[0] == "t-10"
    assert loaded_recent[-1] == f"t-{_MODULE._MAX_RECENT_CONTENT_TOKENS + 9}"


def test_append_recent_content_token_avoids_duplicates() -> None:
    tokens = ["a", "b"]

    _MODULE._append_recent_content_token(tokens, "b")
    _MODULE._append_recent_content_token(tokens, "c")

    assert tokens == ["a", "b", "c"]
