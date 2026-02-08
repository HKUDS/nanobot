import pytest
from nanobot.agent.tools.reasoning import SequentialThinkingTool

@pytest.mark.asyncio
async def test_sequential_thinking_basic_flow():
    tool = SequentialThinkingTool()
    
    # Step 1: Initial plan
    result = await tool.execute(
        thought="I need to analyze the project structure.",
        next_thought_needed=True,
        thought_number=1,
        total_thoughts=3
    )
    assert "Thought 1/3" in result
    assert "I need to analyze the project structure" in result
    assert "Status: continuing" in result

    # Step 2: Execution thought
    result = await tool.execute(
        thought="I will list the files in the root directory.",
        next_thought_needed=False,
        thought_number=2,
        total_thoughts=3
    )
    assert "Thought 2/3" in result
    assert "Status: ready to act" in result

@pytest.mark.asyncio
async def test_sequential_thinking_revision():
    tool = SequentialThinkingTool()
    
    # Original thought
    await tool.execute(
        thought="I will read file A.",
        next_thought_needed=True,
        thought_number=1,
        total_thoughts=2
    )
    
    # Revision
    result = await tool.execute(
        thought="Actually, I should read file B first.",
        next_thought_needed=True,
        thought_number=2,
        total_thoughts=3,
        is_revision=True,
        revises_thought=1
    )
    assert "Thought 2/3" in result
    assert "Rev. 1" in result
    assert "Status: continuing" in result

@pytest.mark.asyncio
async def test_sequential_thinking_branching():
    tool = SequentialThinkingTool()
    
    # Branching
    result = await tool.execute(
        thought="Exploring alternative approach.",
        next_thought_needed=True,
        thought_number=3,
        total_thoughts=5,
        branch_from_thought=1,
        branch_id="alt-1"
    )
    assert "Thought 3/5" in result
    assert "Branch alt-1 from 1" in result
