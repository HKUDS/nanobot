commit 83ccf5605e21358fd0c2e89f3a92df15ca5e9811
Author: comadreja <comadreja@email.com>
Date:   Thu Mar 26 20:43:44 2026 -0500

    fix: handle nullable JSON Schema params in MCP tools
    
    Cherry-picked from upstream 0b1beb0e. Fixes TypeError when MCP tools
    have nullable parameters in their JSON Schema definitions.
    
    Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

diff --git a/tests/test_tool_validation.py b/tests/test_tool_validation.py
index 1d822b3e..e817f37c 100644
--- a/tests/test_tool_validation.py
+++ b/tests/test_tool_validation.py
@@ -406,3 +406,64 @@ async def test_exec_timeout_capped_at_max() -> None:
     # Should not raise — just clamp to 600
     result = await tool.execute(command="echo ok", timeout=9999)
     assert "Exit code: 0" in result
+
+
+# --- _resolve_type and nullable param tests ---
+
+
+def test_resolve_type_simple_string() -> None:
+    """Simple string type passes through unchanged."""
+    assert Tool._resolve_type("string") == "string"
+
+
+def test_resolve_type_union_with_null() -> None:
+    """Union type ['string', 'null'] resolves to 'string'."""
+    assert Tool._resolve_type(["string", "null"]) == "string"
+
+
+def test_resolve_type_only_null() -> None:
+    """Union type ['null'] resolves to None (no non-null type)."""
+    assert Tool._resolve_type(["null"]) is None
+
+
+def test_resolve_type_none_input() -> None:
+    """None input passes through as None."""
+    assert Tool._resolve_type(None) is None
+
+
+def test_validate_nullable_param_accepts_string() -> None:
+    """Nullable string param should accept a string value."""
+    tool = CastTestTool(
+        {
+            "type": "object",
+            "properties": {"name": {"type": ["string", "null"]}},
+        }
+    )
+    errors = tool.validate_params({"name": "hello"})
+    assert errors == []
+
+
+def test_validate_nullable_param_accepts_none() -> None:
+    """Nullable string param should accept None."""
+    tool = CastTestTool(
+        {
+            "type": "object",
+            "properties": {"name": {"type": ["string", "null"]}},
+        }
+    )
+    errors = tool.validate_params({"name": None})
+    assert errors == []
+
+
+def test_cast_nullable_param_no_crash() -> None:
+    """cast_params should not crash on nullable type (the original bug)."""
+    tool = CastTestTool(
+        {
+            "type": "object",
+            "properties": {"name": {"type": ["string", "null"]}},
+        }
+    )
+    result = tool.cast_params({"name": "hello"})
+    assert result["name"] == "hello"
+    result = tool.cast_params({"name": None})
+    assert result["name"] is None
