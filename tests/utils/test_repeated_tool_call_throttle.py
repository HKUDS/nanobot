from nanobot.utils.runtime import repeated_tool_call_error, tool_call_signature


def test_tool_call_signature_stability():
    arg1 = {"a": 1, "b": 2}
    arg2 = {"b": 2, "a": 1}
    assert tool_call_signature("dummy_tool", arg1) == tool_call_signature("dummy_tool", arg2)
    assert tool_call_signature("dummy", {"x": 1}) != tool_call_signature("dummy", {"y": 1})

def test_tool_call_signature_not_dict():
    assert tool_call_signature("dummy_tool", "string") == "dummy_tool:none"

def test_tool_call_signature_list():
    assert tool_call_signature("dummy", [1, 2, 3]) == "dummy:none"

def test_tool_call_signature_none():
    assert tool_call_signature("dummy", None) == "dummy:none"
    assert tool_call_signature("dummy", 123) == "dummy:none"

def test_tool_call_signature_external_lookups():
    assert tool_call_signature("web_search", {"query": "hello"}) is None

def test_tool_call_signature_web_fetch():
    assert tool_call_signature("web_fetch", {"url": "https://foo.com"}) is None

def test_repeated_tool_call_error_under_limit():
    args = {"test": "abc"}
    counts = {tool_call_signature("my_tool", args): 1}

    res1 = repeated_tool_call_error("my_tool", args, counts)
    assert res1 is None

def test_repeated_tool_call_error_over_limit():
    args = {"test": "abc"}
    counts = {tool_call_signature("my_tool", args): 2}

    res = repeated_tool_call_error("my_tool", args, counts)
    assert res is not None
    assert "blocked" in res.lower()

def test_repeated_tool_call_error_diff_tools():
    counts = {tool_call_signature("tool_a", {"a": 1}): 2}
    res = repeated_tool_call_error("tool_b", {"a": 1}, counts)
    assert res is None

def test_repeated_tool_call_error_diff_args():
    counts = {tool_call_signature("tool_a", {"a": 1}): 2}
    res = repeated_tool_call_error("tool_a", {"b": 2}, counts)
    assert res is None

def test_repeated_tool_call_error_excluded_tools_dont_block():
    counts = {tool_call_signature("web_search", {"query": "test"}): 2}
    res = repeated_tool_call_error("web_search", {"query": "test"}, counts)
    assert res is None

def test_signature_unserializable_objects():
    class DummyObj:
        def __str__(self): return "custom"

    arg = {"obj": DummyObj()}
    sig = tool_call_signature("tool", arg)
    assert sig is not None

def test_tool_call_signature_empty_dict():
    assert tool_call_signature("tool", {}) == "tool:{}"
