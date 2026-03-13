import asyncio
import os
import sys
import traceback


# Define load_env_file function BEFORE imports
def load_env_file(env_path):
    """Simple env file loader"""
    if not os.path.exists(env_path):
        print(f"Warning: .env file not found at {env_path}")
        return

    print(f"Loading environment from {env_path}...")
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                # Remove inline comments
                if "#" in value:
                    value = value.split("#", 1)[0]
                value = value.strip().strip('"').strip("'")
                # Only set if not already set (optional, but good practice usually)
                if key not in os.environ:
                    os.environ[key] = value
                    if "SEEKDB" in key:  # Debug log for relevant keys
                        print(f"  Loaded {key}")


# Load environment variables BEFORE importing raganything
# Assuming relative path from BOT/nanobot/scripts to RAG/RAG-Anything
# scripts/.. -> nanobot/
# nanobot/.. -> BOT/
# BOT/.. -> sun_ai/
# then -> RAG/RAG-Anything/.env
try:
    rag_env_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../RAG/RAG-Anything/.env")
    )
    load_env_file(rag_env_path)
except Exception as e:
    print(f"Error loading env: {e}")

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from raganything.sunteco.sunteco_rag_anything import CustomRAGAnything  # ty:ignore[unresolved-import]
except ImportError:
    print("Error: Could not import CustomRAGAnything. Ensure raganything is installed/accessible.")
    sys.exit(1)


async def main():
    print("Initializing RAG instance with default config...")

    # Config from nanobot/data/config.json
    working_dir = os.path.abspath("/home/sunteco/phuongdd/sun_ai/RAG/RAG-Anything/rag_storage")

    rag = CustomRAGAnything(
        working_dir=working_dir,
        llm_binding="openai",
        llm_model_name="Apertis/ministral-8b-2512",
        llm_base_url="http://100.92.219.30:3505/openai/v1",
        llm_api_key="sk-bf-6122bdad-df9a-4c9c-957e-47124ac97574",
        embed_binding="jina",
        embed_model_name="jina-v4",
        embed_dimension=1024,
        embed_base_url="http://100.84.211.80:3100/v1",
        # embedApiKey is empty (or commented out) in .env for jina-v4 endpoint
        embed_api_key="",
    )
    print("RAG Instance created.")

    import lightrag

    print(f"DTO - LightRAG file: {lightrag.__file__}")

    # Use a real query that should have results
    query = "Sunteco virtual machine services"
    print(f"Querying: '{query}'")

    try:
        result = await rag.aquery(query, mode="mix")
        print("------- RAG RESULT -------")
        print(result)
        print("--------------------------")
        if not result or str(result) == "None":
            print("WARNING: Result is None or empty. This confirms the issue.")
            print("Check ingestion status or query formulation.")
        else:
            print("SUCCESS: Received data from RAG.")
    except Exception as e:
        print(f"Error querying RAG: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
