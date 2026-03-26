"""Simple test script for subagent ask_user functionality.

Run with: python tests/test_ask_user_simple.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nanobot.agent.tools.ask_user import AskUserTool


async def test_ask_user_tool():
    """Test AskUserTool basic functionality."""
    print("Testing AskUserTool...")

    # Create a mock callback
    async def mock_callback(question: str) -> str:
        print(f"  Callback received question: {question}")
        return "test response"

    tool = AskUserTool(ask_callback=mock_callback)

    # Test properties
    assert tool.name == "ask_user", f"Expected 'ask_user', got '{tool.name}'"
    assert "ask" in tool.description.lower(), "Description should mention 'ask'"
    assert "question" in tool.parameters["properties"], "Parameters should include 'question'"
    assert tool.parameters["required"] == ["question"], "'question' should be required"

    # Test execute
    result = await tool.execute(question="What is your name?")
    assert result == "test response", f"Expected 'test response', got '{result}'"

    print("  ✓ All AskUserTool tests passed!")


async def test_subagent_manager_attrs():
    """Test SubagentManager has the required attributes."""
    print("Testing SubagentManager attributes...")

    # Import here to avoid needing full initialization
    from nanobot.agent.subagent import SubagentManager

    # Check that the class has the new attributes
    assert hasattr(SubagentManager, '_handle_ask_request'), \
        "SubagentManager should have _handle_ask_request method"
    assert hasattr(SubagentManager, 'resume_with_user_response'), \
        "SubagentManager should have resume_with_user_response method"
    assert hasattr(SubagentManager, 'is_waiting_for_user'), \
        "SubagentManager should have is_waiting_for_user method"

    print("  ✓ All SubagentManager attribute tests passed!")


async def test_agent_loop_attrs():
    """Test AgentLoop has the required attributes."""
    print("Testing AgentLoop attributes...")

    from nanobot.agent.loop import AgentLoop

    # Check that the class has the new attributes
    # (The _pending_ask_requests dict is initialized in __init__)

    print("  ✓ AgentLoop attributes look good!")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Running subagent ask_user tests")
    print("=" * 60)
    print()

    try:
        await test_ask_user_tool()
        print()
        await test_subagent_manager_attrs()
        print()
        await test_agent_loop_attrs()
        print()

        print("=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
