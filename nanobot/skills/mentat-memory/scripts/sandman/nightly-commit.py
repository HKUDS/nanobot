#!/usr/bin/env python3
"""
Sandman Nightly Git Commit
Commits all memory changes once per night to protect against corruption.
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

def main():
    memory_dir = Path(__file__).parent.parent.parent / "memory"
    
    try:
        # Change to memory directory
        subprocess.run(["git", "status"], cwd=memory_dir, check=True, capture_output=True)
        
        # Stage all changes
        subprocess.run(["git", "add", "-A"], cwd=memory_dir, check=True)
        
        # Check if there are changes to commit
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=memory_dir,
            capture_output=True,
            text=True,
            check=True
        )
        
        if not status.stdout.strip():
            print("No changes to commit")
            return 0
        
        # Create commit with timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M MST")
        commit_msg = f"Memory snapshot: {timestamp}"
        
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=memory_dir,
            check=True
        )
        
        print(f"✅ Memory committed: {commit_msg}")
        return 0
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Git commit failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
