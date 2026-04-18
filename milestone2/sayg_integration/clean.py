import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import MEMORY_DIR, LOG_DIR, HEAP_DIR, DATA_SEGMENT_DIR, PUBLIC_MEMORY_DIR, STACK_DIR

def clean():
    print("=" * 70)
    print("Cleaning SAYG-Mem Integration Environment...")
    print("=" * 70)

    dirs_to_clean = [
        ("heaps", HEAP_DIR),
        ("stacks", STACK_DIR),
        ("data_segment", DATA_SEGMENT_DIR),
        ("public_memory", PUBLIC_MEMORY_DIR),
        ("memory (all)", MEMORY_DIR),
        ("logs", LOG_DIR),
    ]

    for name, dir_path in dirs_to_clean:
        dir_path = Path(dir_path)
        if dir_path.exists():
            if name == "memory (all)":
                shutil.rmtree(dir_path)
                dir_path.mkdir(parents=True, exist_ok=True)
                print(f"  Removed & Recreated: {name}")
            else:
                for file in dir_path.iterdir():
                    if file.is_file():
                        file.unlink()
                print(f"  Cleaned: {name}")
        else:
            dir_path.mkdir(parents=True, exist_ok=True)
            print(f"  Created: {name}")

    timing_log = LOG_DIR / "timing_logs.jsonl"
    if timing_log.exists():
        timing_log.unlink()
        print(f"  Removed: timing_logs.jsonl")

    print("\n" + "=" * 70)
    print("Environment cleaned successfully!")
    print("=" * 70)

if __name__ == "__main__":
    clean()
