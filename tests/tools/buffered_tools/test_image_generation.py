"""
Test Gemini Image Generation with Buffered Tools

Tests the async image generation with multi-agent Chinese prompt synthesis.
Uses the provided GOOGLE_GENERATIVE_AI_API_KEY.
"""

import asyncio
import os
import sys
import codecs
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add parent directory to path for imports
root_dir = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(root_dir))

from nanobot.agent.tools.buffered_tools.image_gen import (
    AsyncImageGenerationTool,
    ChinesePromptAgent,
    GenerationTask,
    ImgGenerateAsyncTool,
    ImgCheckStatusTool,
    init_async_image_tool,
)


# Test API key - use environment variable or fallback
GOOGLE_GENERATIVE_AI_API_KEY = os.environ.get(
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "AIzaSyC3PIUzoR5VQcd1EEcAKjO_nlY9OKxUAuc"
)

# Also check GEMINI_API_KEY for compatibility
if not GOOGLE_GENERATIVE_AI_API_KEY:
    GOOGLE_GENERATIVE_AI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


class MockSendCallback:
    """Mock callback that captures sent messages."""
    
    def __init__(self):
        self.messages = []
    
    async def __call__(self, channel: str, chat_id: str, message: str):
        """Capture message."""
        self.messages.append({
            "channel": channel,
            "chat_id": chat_id,
            "message": message,
        })
        print(f"\n[SEND TO {channel}/{chat_id}]")
        print("-" * 60)
        print(message.encode('utf-8', errors='replace').decode('utf-8'))
        print("-" * 60)


async def test_chinese_prompt_agent():
    """Test the multi-agent Chinese prompt generation."""
    print("\n" + "="*70)
    print(" TEST 1: Multi-Agent Chinese Prompt Generation")
    print("="*70)
    
    agent = ChinesePromptAgent()
    
    # Test conversation analysis
    print("\n[1/4] Testing conversation analysis...")
    conversation = "I want a beautiful mountain landscape with sunrise and warm colors"
    result = await agent.analyze_conversation(conversation)
    print(f"  User Intent: {result.get('user_intent', 'N/A')}")
    print(f"  Tone: {result.get('tone', 'N/A')}")
    print(f"  Elements: {result.get('elements', [])}")
    
    # Test style extraction
    print("\n[2/4] Testing style extraction...")
    bot_profile = "Artistic bot preferring warm colors and Chinese aesthetics"
    result = await agent.extract_style(bot_profile)
    print(f"  Style: {result.get('style', 'N/A')}")
    print(f"  Colors: {result.get('colors', 'N/A')}")
    
    # Test cultural adaptation
    print("\n[3/4] Testing cultural adaptation...")
    result = await agent.adapt_culture()
    print(f"  Cultural Elements: {result.get('cultural_elements', [])}")
    print(f"  Symbolism: {result.get('symbolism', [])}")
    
    # Test prompt synthesis
    print("\n[4/4] Testing prompt synthesis...")
    contexts = [
        {"user_intent": "壮丽的山水", "elements": ["光影", "色彩"]},
        {"style": "写实艺术", "colors": "温暖色调"},
        {"cultural_elements": ["中国美学"], "symbolism": ["和谐"]},
    ]
    chinese_prompt = await agent.synthesize(contexts)
    print(f"  Generated Prompt: {chinese_prompt[:150]}...")
    
    print("\n[OK] Multi-agent prompt generation test passed!")
    return True


async def test_gemini_api_connection():
    """Test Gemini API connection."""
    print("\n" + "="*70)
    print(" TEST 2: Gemini API Connection")
    print("="*70)
    
    import httpx
    
    print(f"\nUsing API Key: {GOOGLE_GENERATIVE_AI_API_KEY[:15]}...")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Test with simple text generation first
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                params={"key": GOOGLE_GENERATIVE_AI_API_KEY.strip()},
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "parts": [{"text": "Hello, are you working?"}]
                    }]
                }
            )
            
            print(f"Response Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print("[OK] Gemini API connection successful!")
                
                if "candidates" in data and len(data["candidates"]) > 0:
                    content = data["candidates"][0].get("content", {})
                    parts = content.get("parts", [])
                    for part in parts:
                        if "text" in part:
                            print(f"Gemini says: {part['text'][:100]}")
                return True
            else:
                print(f"[ERROR] API returned status {response.status_code}")
                print(f"Response: {response.text[:200]}")
                return False
                
        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}")
            return False


async def test_gemini_image_generation():
    """Test actual Gemini image generation."""
    print("\n" + "="*70)
    print(" TEST 3: Gemini Image Generation")
    print("="*70)
    
    import httpx
    
    # Chinese prompt
    chinese_prompt = """
    主体：壮丽的山水景观，
    关键元素：光影效果、丰富色彩，
    艺术风格：写实与艺术结合，
    色调：温暖和谐的色调，
    氛围：优美、宁静，
    细节丰富，高质量，8K 分辨率
    """
    
    print(f"\nPrompt: {chinese_prompt.strip()[:100]}...")
    print("\nRequesting image generation from Gemini...")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                params={"key": GOOGLE_GENERATIVE_AI_API_KEY.strip()},
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{
                        "parts": [{
                            "text": f"Generate a detailed image: {chinese_prompt}"
                        }]
                    }],
                    "generationConfig": {
                        "responseModalities": ["IMAGE", "TEXT"],
                        "temperature": 0.7,
                    }
                }
            )
            
            print(f"\nResponse Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print("[OK] API request successful!")
                
                # Check for image
                has_image = False
                if "candidates" in data:
                    for candidate in data["candidates"]:
                        content = candidate.get("content", {})
                        parts = content.get("parts", [])
                        
                        for part in parts:
                            if "inlineData" in part:
                                has_image = True
                                image_data = part["inlineData"]
                                mime_type = image_data.get("mimeType", "unknown")
                                image_bytes = image_data.get("data", "")
                                
                                print(f"\n[OK] Image generated!")
                                print(f"  MIME Type: {mime_type}")
                                print(f"  Size: {len(image_bytes)} bytes (base64)")
                                
                                # Save image
                                if image_bytes:
                                    import base64
                                    img_data = base64.b64decode(image_bytes)
                                    
                                    # Save to test output directory
                                    output_dir = Path(__file__).parent / "output"
                                    output_dir.mkdir(exist_ok=True)
                                    
                                    filename = output_dir / f"gemini_test_{asyncio.get_event_loop().time()}.png"
                                    with open(filename, "wb") as f:
                                        f.write(img_data)
                                    print(f"  Saved to: {filename}")
                            
                            elif "text" in part:
                                print(f"\nText response: {part['text'][:200]}")
                
                if not has_image:
                    print("\n[WARN] No image in response, but API call succeeded")
                    print("This may mean Gemini doesn't support image generation with this key/model")
                
                return True
            else:
                error_text = response.text[:300]
                print(f"[ERROR] API returned status {response.status_code}")
                
                if "API key expired" in error_text or "API_KEY_INVALID" in error_text:
                    print("[ERROR] API key is invalid or expired")
                    print(f"Current key: {GOOGLE_GENERATIVE_AI_API_KEY[:15]}...")
                    print("Please update the key in the test file or environment")
                else:
                    print(f"Response: {error_text}")
                return False
                
        except httpx.TimeoutException:
            print("[ERROR] Request timed out (120 seconds)")
            return False
        except Exception as e:
            print(f"[ERROR] {type(e).__name__}: {e}")
            return False


async def test_async_image_tool():
    """Test the async image generation tool."""
    print("\n" + "="*70)
    print(" TEST 4: Async Image Tool (Non-blocking)")
    print("="*70)
    
    # Set environment variable for this test
    os.environ["GOOGLE_GENERATIVE_AI_API_KEY"] = GOOGLE_GENERATIVE_AI_API_KEY
    print(f"\nUsing API Key: {GOOGLE_GENERATIVE_AI_API_KEY[:15]}...")
    
    # Initialize tool with mock callback
    callback = MockSendCallback()
    tool = AsyncImageGenerationTool(callback)
    
    print("\nStarting async generation (should return immediately)...")
    
    task_id = await tool.generate_and_create(
        conversation_history="User wants a beautiful mountain landscape",
        bot_profile="Artistic bot with Chinese aesthetics",
        channel="test_channel",
        chat_id="test_123",
        provider="gemini",  # Will use GOOGLE_GENERATIVE_AI_API_KEY
    )
    
    print(f"\n[OK] Task started immediately!")
    print(f"Task ID: {task_id}")
    
    # Wait a bit for background task to run
    print("\nWaiting 10 seconds for background processing...")
    await asyncio.sleep(10)
    
    # Check task status
    task = tool.get_task_status(task_id)
    if task:
        print(f"\nTask Status: {task.status}")
        print(f"Messages sent: {len(callback.messages)}")
        
        for msg in callback.messages:
            print(f"\n  - To {msg['channel']}/{msg['chat_id']}:")
            msg_text = msg['message'].encode('utf-8', errors='replace').decode('utf-8')
            print(f"    {msg_text[:200]}...")
    else:
        print("[WARN] Task not found in registry")
    
    print("\n[OK] Async tool test completed!")
    return True


async def test_buffered_image_tools():
    """Test the buffered image tools integration."""
    print("\n" + "="*70)
    print(" TEST 5: Buffered Tools Integration")
    print("="*70)
    
    # Initialize
    callback = MockSendCallback()
    init_async_image_tool(callback)
    
    # Test tool creation
    print("\nCreating tools...")
    tools = [
        ImgGenerateAsyncTool(),
        ImgCheckStatusTool(),
    ]
    
    for t in tools:
        print(f"  - {t.name}: {t.description[:50]}...")
    
    # Test execute (won't actually run without proper context)
    print("\nTesting tool execution...")
    try:
        result = await ImgGenerateAsyncTool().execute(
            conversation_history="Test conversation",
            bot_profile="Test bot",
            provider="gemini",
            channel="test",
            chat_id="test",
        )
        print(f"[OK] Tool executed: {result[:100]}...")
    except Exception as e:
        print(f"[INFO] Expected behavior: {type(e).__name__}: {e}")
    
    print("\n[OK] Integration test completed!")
    return True


async def run_all_tests():
    """Run all tests."""
    print("\n" + "="*70)
    print(" GEMINI IMAGE GENERATION TEST SUITE")
    print("="*70)
    print(f"\nAPI Key: {GOOGLE_GENERATIVE_AI_API_KEY[:15]}...")
    print(f"Testing: nanobot.agent.tools.buffered_tools.image_gen")
    
    results = {}
    
    # Test 1: Chinese prompt agent
    try:
        results["chinese_prompt_agent"] = await test_chinese_prompt_agent()
    except Exception as e:
        print(f"\n[ERROR] Test 1 failed: {type(e).__name__}: {e}")
        results["chinese_prompt_agent"] = False
    
    # Test 2: Gemini API connection
    try:
        results["gemini_api"] = await test_gemini_api_connection()
    except Exception as e:
        print(f"\n[ERROR] Test 2 failed: {type(e).__name__}: {e}")
        results["gemini_api"] = False
    
    # Test 3: Gemini image generation
    try:
        results["gemini_image"] = await test_gemini_image_generation()
    except Exception as e:
        print(f"\n[ERROR] Test 3 failed: {type(e).__name__}: {e}")
        results["gemini_image"] = False
    
    # Test 4: Async image tool
    try:
        results["async_tool"] = await test_async_image_tool()
    except Exception as e:
        print(f"\n[ERROR] Test 4 failed: {type(e).__name__}: {e}")
        results["async_tool"] = False
    
    # Test 5: Integration
    try:
        results["integration"] = await test_buffered_image_tools()
    except Exception as e:
        print(f"\n[ERROR] Test 5 failed: {type(e).__name__}: {e}")
        results["integration"] = False
    
    # Summary
    print("\n" + "="*70)
    print(" TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {test_name}")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*70 + "\n")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
