import sys
from pathlib import Path
sys.path.append(str(Path.cwd()))

from nanobot.agent.context import ContextBuilder

def test_context():
    # Setup workspace path (assuming it exists relative to CWD)
    workspace = Path("workspace")
    cb = ContextBuilder(workspace)
    try:
        identity = cb._get_identity()
        print("--- Identity Section ---")
        print(identity)
        print("------------------------")
        
        if "Europe/Moscow" in identity and "User:" in identity:
            print("SUCCESS: Timezone found in context.")
        else:
            print("FAILURE: Timezone NOT found in context.")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_context()
