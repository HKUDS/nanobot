"""
Verification script for RagTool integration.
Tests if the tool can be instantiated and if RAG availability is detected.
"""

import sys
import os
import asyncio

# Ensure project root is in path
sys.path.append(os.getcwd())

# Set required env vars for RAGAnything init
os.environ.setdefault("FALKORDB_PORT", "6379")
os.environ.setdefault("FALKORDB_DATABASE", "0")
os.environ.setdefault("GRAPH_TYPE", "FALKORDB")

from nanobot.agent.tools.rag import RagTool


async def test_rag_tool():
    print(">>> Testing RagTool instantiation...")
    try:
        tool = RagTool()
        print(f"✅ Tool created: {tool.name}")
        print(f"📄 Description: {tool.description[:50]}...")

        # Check internal availability flag
        from nanobot.agent.tools.rag import RAG_AVAILABLE

        if RAG_AVAILABLE:
            print("✅ RAG-Anything is DETECTED and AVAILABLE.")
        else:
            print("⚠️ RAG-Anything is NOT AVAILABLE (Import failed).")
            print("   (This is expected if deps are missing, but tool handles it gracefully)")

        # Test basic validation
        params = {"query": "test query"}
        errors = tool.validate_params(params)
        if not errors:
            print("✅ Parameter validation passed.")
        else:
            print(f"❌ Parameter validation failed: {errors}")

    except Exception as e:
        print(f"❌ Failed to instantiate RagTool: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_rag_tool())
