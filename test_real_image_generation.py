"""
Test if Gemini API actually generates images

This script tests the real Gemini/Imagen API for image generation.
"""

import asyncio
import os
import sys

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()


async def test_gemini_image_generation():
    """Test actual Gemini image generation"""
    
    # Get API key
    api_key = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        print("[FAIL] No Gemini API key found!")
        print("\nSet one of these environment variables:")
        print("  - GOOGLE_GENERATIVE_AI_API_KEY")
        print("  - GEMINI_API_KEY")
        return False
    
    print(f"[OK] Found Gemini API key: {api_key[:15]}...")
    
    import httpx
    
    prompt = "A beautiful mountain landscape at sunset"
    
    print(f"\nSending request to Gemini API...")
    print(f"Prompt: {prompt}")
    
    # Try Imagen 3 endpoint
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1/models/imagen-3.0-generate-001:predict",
                params={"key": api_key.strip()},
                headers={
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": prompt,
                    "sampleCount": 1,
                    "aspectRatio": "1:1",
                    "negativePrompt": "",
                }
            )
            
            print(f"\nResponse status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"[OK] Success! Response data keys: {data.keys()}")
                
                if "predictions" in data and len(data["predictions"]) > 0:
                    image_bytes = data["predictions"][0].get("bytesBase64Encoded", "")
                    if image_bytes:
                        print(f"[OK] Image generated! Base64 length: {len(image_bytes)}")
                        
                        # Save the image
                        import base64
                        from pathlib import Path
                        
                        output_dir = Path("test_output")
                        output_dir.mkdir(exist_ok=True)
                        
                        img_data = base64.b64decode(image_bytes)
                        output_file = output_dir / "gemini_test.png"
                        
                        with open(output_file, "wb") as f:
                            f.write(img_data)
                        
                        print(f"[OK] Image saved to: {output_file}")
                        print(f"   File size: {len(img_data)} bytes")
                        return True
                    else:
                        print("[FAIL] No image data in response")
                else:
                    print(f"[FAIL] No predictions in response: {data}")
            else:
                print(f"[FAIL] API Error: {response.status_code}")
                print(f"Response: {response.text[:500]}")
                
                # Check for specific error messages
                error_text = response.text.lower()
                if "billing" in error_text or "payment" in error_text:
                    print("\n[WARNING] This appears to be a billing/subscription issue.")
                    print("   Gemini image generation may require a paid Google Cloud account.")
                elif "permission" in error_text or "unauthorized" in error_text:
                    print("\n[WARNING] Permission denied. Your API key may not have image generation access.")
                elif "quota" in error_text:
                    print("\n[WARNING] Quota exceeded. Check your API usage limits.")
                
        except Exception as e:
            print(f"[FAIL] Error: {e}")
    
    return False


async def test_openai_image_generation():
    """Test actual OpenAI DALL-E 3 image generation"""
    
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        print("\n[FAIL] No OpenAI API key found!")
        return False
    
    print(f"\n[OK] Found OpenAI API key: {api_key[:15]}...")
    
    import httpx
    
    prompt = "A beautiful mountain landscape at sunset"
    
    print(f"\nSending request to OpenAI DALL-E 3 API...")
    print(f"Prompt: {prompt}")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "dall-e-3",
                    "prompt": prompt,
                    "n": 1,
                    "size": "1024x1024",
                    "quality": "standard",
                }
            )
            
            print(f"\nResponse status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"[OK] Success!")
                
                if "data" in data and len(data["data"]) > 0:
                    image_url = data["data"][0]["url"]
                    print(f"[OK] Image URL: {image_url}")
                    
                    # Download and save the image
                    from pathlib import Path
                    
                    output_dir = Path("test_output")
                    output_dir.mkdir(exist_ok=True)
                    
                    # Download image
                    img_response = await client.get(image_url)
                    if img_response.status_code == 200:
                        output_file = output_dir / "openai_test.png"
                        with open(output_file, "wb") as f:
                            f.write(img_response.content)
                        
                        print(f"[OK] Image saved to: {output_file}")
                        print(f"   File size: {len(img_response.content)} bytes")
                        return True
                else:
                    print(f"[FAIL] No image data in response: {data}")
            else:
                print(f"[FAIL] API Error: {response.status_code}")
                print(f"Response: {response.text[:500]}")
                
        except Exception as e:
            print(f"[FAIL] Error: {e}")
    
    return False


async def main():
    print("=" * 80)
    print("REAL IMAGE GENERATION API TEST")
    print("=" * 80)
    
    # Check environment
    print("\nEnvironment Check:")
    print(f"  GOOGLE_GENERATIVE_AI_API_KEY: {'[SET]' if os.getenv('GOOGLE_GENERATIVE_AI_API_KEY') else '[NOT SET]'}")
    print(f"  GEMINI_API_KEY: {'[SET]' if os.getenv('GEMINI_API_KEY') else '[NOT SET]'}")
    print(f"  OPENAI_API_KEY: {'[SET]' if os.getenv('OPENAI_API_KEY') else '[NOT SET]'}")
    
    # Test Gemini
    print("\n" + "=" * 80)
    print("TEST 1: Gemini/Imagen API")
    print("=" * 80)
    gemini_result = await test_gemini_image_generation()
    
    # Test OpenAI
    print("\n" + "=" * 80)
    print("TEST 2: OpenAI DALL-E 3 API")
    print("=" * 80)
    openai_result = await test_openai_image_generation()
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Gemini/Imagen:  {'[OK] WORKS' if gemini_result else '[FAIL] NO API KEY or FAILED'}")
    print(f"OpenAI DALL-E 3: {'[OK] WORKS' if openai_result else '[FAIL] NO API KEY or FAILED'}")
    
    if not gemini_result and not openai_result:
        print("\n[WARNING] No working image generation API found.")
        print("   Add an API key and re-run this test.")


if __name__ == "__main__":
    asyncio.run(main())
