"""
Simple test to verify new features:
1. Usage tracker
2. Ollama provider (import test)
3. OllamaWebSearchTool (import test)
"""

def test_usage_tracker():
    """Test usage tracker basic functionality."""
    from nanobot.usage.tracker import UsageTracker
    import tempfile
    from pathlib import Path
    
    # Create temporary directory for test
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = UsageTracker(data_dir=Path(tmpdir))
        
        # Track some usage
        tracker.track(
            session_key="test:session",
            model="test-model",
            prompt_tokens=100,
            completion_tokens=50,
        )
        
        # Verify total
        total = tracker.get_total()
        assert total["prompt_tokens"] == 100
        assert total["completion_tokens"] == 50
        assert total["total_tokens"] == 150
        assert total["call_count"] == 1
        
        # Verify session
        session = tracker.get_session("test:session")
        assert session is not None
        assert session["total_tokens"] == 150
        
        print("✓ Usage tracker test passed")


def test_ollama_provider_import():
    """Test that Ollama provider can be imported."""
    try:
        from nanobot.providers.ollama_provider import OllamaProvider
        print("✓ Ollama provider import successful")
        
        # Check basic initialization
        provider = OllamaProvider(default_model="qwen3:4b")
        assert provider.get_default_model() == "qwen3:4b"
        print("✓ Ollama provider initialization successful")
    except Exception as e:
        print(f"✗ Ollama provider test failed: {e}")
        raise


def test_ollama_web_search_tool_import():
    """Test that OllamaWebSearchTool can be imported."""
    try:
        from nanobot.agent.tools.web import OllamaWebSearchTool
        print("✓ OllamaWebSearchTool import successful")
        
        # Check basic initialization
        tool = OllamaWebSearchTool()
        assert tool.name == "ollama_web_search"
        print("✓ OllamaWebSearchTool initialization successful")
    except Exception as e:
        print(f"✗ OllamaWebSearchTool test failed: {e}")
        raise


def test_config_schema():
    """Test configuration schema includes new fields."""
    from nanobot.config.schema import Config, UsageAlertConfig, OllamaWebSearchConfig
    
    # Create default config
    config = Config()
    
    # Check usage alert config
    assert hasattr(config, "usage_alert")
    assert isinstance(config.usage_alert, UsageAlertConfig)
    assert config.usage_alert.daily_limit == 1000000
    print("✓ UsageAlertConfig in schema")
    
    # Check ollama provider config
    assert hasattr(config.providers, "ollama")
    print("✓ Ollama provider in schema")
    
    # Check ollama web search config
    assert hasattr(config.tools.web, "ollama_search")
    assert isinstance(config.tools.web.ollama_search, OllamaWebSearchConfig)
    print("✓ OllamaWebSearchConfig in schema")


if __name__ == "__main__":
    print("Running feature tests...\n")
    
    test_usage_tracker()
    test_ollama_provider_import()
    test_ollama_web_search_tool_import()
    test_config_schema()
    
    print("\n✅ All tests passed!")
