"""
Standalone Test Script for Image Generation Tools

Tests the buffered image generation tools as function calls without the full bot.
"""

import asyncio
import os
import sys

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from nanobot.agent.tools.buffered_tools.image_gen import (
    create_buffered_image_tools,
    create_async_image_tools,
    init_async_image_tool,
)


async def send_to_channel(channel: str, chat_id: str, message: str):
    """Mock callback for sending messages to channel."""
    print(f"\n📤 [SEND TO {channel}:{chat_id}]")
    print(f"{message}")
    print("-" * 80)


async def test_basic_buffered_tools():
    """Test basic buffered image generation tools."""
    print("\n" + "=" * 80)
    print("TEST 1: Basic Buffered Image Tools")
    print("=" * 80)

    # Create tools
    tools = create_buffered_image_tools()
    print(f"\n[OK] Created {len(tools)} tools:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description[:60]}...")

    # Test img_list_fields
    print("\n" + "-" * 80)
    print("Testing: img_list_fields")
    print("-" * 80)
    list_tool = next(t for t in tools if t.name == "img_list_fields")
    result = await list_tool.execute()
    print(f"Available fields: {result}")

    # Test img_set_field
    print("\n" + "-" * 80)
    print("Testing: img_set_field")
    print("-" * 80)
    set_tool = next(t for t in tools if t.name == "img_set_field")

    test_fields = {
        "subject": "beautiful mountain landscape",
        "description": "Majestic mountains with snow-capped peaks at sunset",
        "style": "realistic photography",
        "mood": "serene and peaceful",
        "lighting": "golden hour, warm sunlight",
        "color_palette": "warm oranges, purples, and blues",
        "resolution": "1024x1024",
        "quality": "hd",
        "provider": "openai",
    }

    for field_name, value in test_fields.items():
        result = await set_tool.execute(field_name=field_name, value=value)
        print(f"  {field_name}: {result}")

    # Test img_get_field
    print("\n" + "-" * 80)
    print("Testing: img_get_field")
    print("-" * 80)
    get_tool = next(t for t in tools if t.name == "img_get_field")
    result = await get_tool.execute(field_name="subject")
    print(f"Subject field: {result}")

    # Test img_get_buffer_state
    print("\n" + "-" * 80)
    print("Testing: img_get_buffer_state")
    print("-" * 80)
    state_tool = next(t for t in tools if t.name == "img_get_buffer_state")
    result = await state_tool.execute()
    print(f"Buffer state:\n{result}")

    # Test img_is_ready
    print("\n" + "-" * 80)
    print("Testing: img_is_ready")
    print("-" * 80)
    ready_tool = next(t for t in tools if t.name == "img_is_ready")
    result = await ready_tool.execute()
    print(f"Ready status: {result}")

    # Test img_fire
    print("\n" + "-" * 80)
    print("Testing: img_fire")
    print("-" * 80)
    fire_tool = next(t for t in tools if t.name == "img_fire")

    # Check if API key is available
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        print("[WARNING] OPENAI_API_KEY not set - skipping actual generation")
        print("Set the environment variable to test actual image generation")
    else:
        print("Generating image... (this may take 30-60 seconds)")
        result = await fire_tool.execute()
        print(f"Generation result:\n{result}")

    # Test img_reset
    print("\n" + "-" * 80)
    print("Testing: img_reset")
    print("-" * 80)
    reset_tool = next(t for t in tools if t.name == "img_reset")
    result = await reset_tool.execute()
    print(f"Reset result: {result}")

    # Verify reset
    result = await get_tool.execute(field_name="subject")
    print(f"Subject after reset: {result}")

    print("\n[OK] Basic buffered tools test completed!")


async def test_async_tools():
    """Test async image generation tools."""
    print("\n" + "=" * 80)
    print("TEST 2: Async Image Generation Tools")
    print("=" * 80)

    # Initialize async tool
    async_tool = init_async_image_tool(send_to_channel)
    print("\n[OK] Initialized async image tool")

    # Create tools
    tools = create_async_image_tools()
    print(f"[OK] Created {len(tools)} async tools:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description[:60]}...")

    # Test img_generate_async
    print("\n" + "-" * 80)
    print("Testing: img_generate_async")
    print("-" * 80)
    gen_tool = next(t for t in tools if t.name == "img_generate_async")

    # Prepare test context
    conversation_history = """
    User: 我想要一张美丽的山水画
    Assistant: 好的，我来为您生成一幅精美的山水画。您喜欢什么风格？
    User: 喜欢中国传统风格，有山有水，云雾缭绕
    """

    bot_profile = "Artistic bot with preference for traditional Chinese aesthetics, warm colors, and cultural elements"

    # Check for API keys
    gemini_key = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not gemini_key and not openai_key:
        print("[WARNING] No API keys found (GOOGLE_GENERATIVE_AI_API_KEY or OPENAI_API_KEY)")
        print("Set environment variables to test actual generation")

        # Test with mock data anyway
        print("\nTesting async flow (will fail without API key)...")
        try:
            result = await gen_tool.execute(
                conversation_history=conversation_history,
                bot_profile=bot_profile,
                provider="openai",
                channel="test",
                chat_id="test123"
            )
            print(f"Task started: {result}")
        except Exception as e:
            print(f"Expected error (no API key): {e}")
    else:
        provider = "gemini" if gemini_key else "openai"
        print(f"Starting async generation with provider: {provider}")

        result = await gen_tool.execute(
            conversation_history=conversation_history,
            bot_profile=bot_profile,
            provider=provider,
            channel="test",
            chat_id="test123"
        )
        print(f"\nTask started: {result}")

        # Wait a bit for background task
        print("\nWaiting for generation to complete...")
        await asyncio.sleep(5)

    # Test img_check_status
    print("\n" + "-" * 80)
    print("Testing: img_check_status")
    print("-" * 80)
    status_tool = next(t for t in tools if t.name == "img_check_status")

    # Try with a mock task ID
    result = await status_tool.execute(task_id="mock123")
    print(f"Status check: {result}")

    print("\n[OK] Async tools test completed!")


async def test_multi_agent_prompt():
    """Test multi-agent Chinese prompt generation."""
    print("\n" + "=" * 80)
    print("TEST 3: Multi-Agent Chinese Prompt Generation")
    print("=" * 80)

    from nanobot.agent.tools.buffered_tools.image_gen import (
        create_buffered_image_tools_with_agents,
        ImgGeneratePromptTool,
        ImgGetChinesePromptTool,
    )

    # Create tools with agents
    tools = create_buffered_image_tools_with_agents()
    print(f"\n[OK] Created {len(tools)} tools with multi-agent support")

    for tool in tools:
        print(f"  - {tool.name}: {tool.description[:60]}...")

    # Test img_generate_prompt
    print("\n" + "-" * 80)
    print("Testing: img_generate_prompt")
    print("-" * 80)
    
    # Find the tool by name
    prompt_tool = None
    for t in tools:
        if t.name == "img_generate_prompt":
            prompt_tool = t
            break
    
    if prompt_tool is None:
        # Create tool directly
        prompt_tool = ImgGeneratePromptTool()
        print("Created ImgGeneratePromptTool directly")

    conversation_history = """
    User: I want a beautiful image of a mountain landscape at sunset
    Assistant: What style would you prefer?
    User: Realistic photography with warm colors
    """

    bot_profile = "Artistic assistant with preference for nature photography"

    result = await prompt_tool.execute(
        conversation_history=conversation_history,
        bot_profile=bot_profile
    )
    print(f"Multi-agent analysis:\n{result}")

    # Test img_get_chinese_prompt
    print("\n" + "-" * 80)
    print("Testing: img_get_chinese_prompt")
    print("-" * 80)
    
    # Find the tool by name
    chinese_tool = None
    for t in tools:
        if t.name == "img_get_chinese_prompt":
            chinese_tool = t
            break
    
    if chinese_tool is None:
        # Create tool directly
        chinese_tool = ImgGetChinesePromptTool()
        print("Created ImgGetChinesePromptTool directly")

    result = await chinese_tool.execute()
    print(f"Chinese prompt:\n{result}")

    print("\n[OK] Multi-agent prompt test completed!")


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("IMAGE GENERATION TOOLS - STANDALONE TEST")
    print("=" * 80)

    # Show available API keys
    print("\nEnvironment Check:")
    print(f"  OPENAI_API_KEY: {'[SET]' if os.getenv('OPENAI_API_KEY') else '[NOT SET]'}")
    print(f"  GOOGLE_GENERATIVE_AI_API_KEY: {'[SET]' if os.getenv('GOOGLE_GENERATIVE_AI_API_KEY') else '[NOT SET]'}")
    print(f"  GEMINI_API_KEY: {'[SET]' if os.getenv('GEMINI_API_KEY') else '[NOT SET]'}")
    print(f"  STABILITY_API_KEY: {'[SET]' if os.getenv('STABILITY_API_KEY') else '[NOT SET]'}")

    # Run tests
    try:
        await test_basic_buffered_tools()
    except Exception as e:
        print(f"\n❌ Error in basic tools test: {e}")
        import traceback
        traceback.print_exc()

    try:
        await test_async_tools()
    except Exception as e:
        print(f"\n❌ Error in async tools test: {e}")
        import traceback
        traceback.print_exc()

    try:
        await test_multi_agent_prompt()
    except Exception as e:
        print(f"\n❌ Error in multi-agent prompt test: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("ALL TESTS COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
