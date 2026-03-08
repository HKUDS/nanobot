#!/bin/bash
# Wrapper for local embedding-based memory search
# Usage: memory-search-tool.sh "your query here"

cd /home/deva/shared
/home/deva/.whisper-venv/bin/python scripts/search-memory.py "$@"
