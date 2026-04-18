import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

MEMORY_DIR = DATA_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

HEAP_DIR = MEMORY_DIR / "heaps"
HEAP_DIR.mkdir(exist_ok=True)

STACK_DIR = MEMORY_DIR / "stacks"
STACK_DIR.mkdir(exist_ok=True)

DATA_SEGMENT_DIR = MEMORY_DIR / "data_segment"
DATA_SEGMENT_DIR.mkdir(exist_ok=True)

PUBLIC_MEMORY_DIR = MEMORY_DIR / "public_memory"
PUBLIC_MEMORY_DIR.mkdir(exist_ok=True)

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")
AGENT_IDS = ["agent_a", "agent_b", "agent_c"]
CONSOLIDATOR_INTERVAL = int(os.environ.get("CONSOLIDATOR_INTERVAL", "10"))
HEAP_THRESHOLD = int(os.environ.get("HEAP_THRESHOLD", "5"))
ENABLE_TIMING = True
TIMING_LOG_PATH = LOG_DIR / "timing_logs.jsonl"
LINES_PER_PAGE = 100
DEDUP_SIMILARITY_THRESHOLD = 0.85
LLM_REQUEST_TIMEOUT = 300.0
