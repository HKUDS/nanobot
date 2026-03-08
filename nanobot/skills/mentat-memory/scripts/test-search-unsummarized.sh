#!/bin/bash
# Test suite for search-unsummarized.py

echo "=== Testing search-unsummarized.py ==="
echo ""

# Test 1: Basic search
echo "Test 1: Basic search (default query)"
python3 scripts/search-unsummarized.py "test query" --top-k 3 2>&1 | head -20
echo ""

# Test 2: JSON output
echo "Test 2: JSON output"
python3 scripts/search-unsummarized.py "test" --json --top-k 1 2>&1 | python3 -m json.tool | head -20
echo ""

# Test 3: No results (high threshold)
echo "Test 3: High threshold (should return few/no results)"
python3 scripts/search-unsummarized.py "test" --min-score 0.9 --top-k 1
echo ""

# Test 4: Cache verification
echo "Test 4: Cache directory status"
if [ -d ".unsummarized-embeddings" ]; then
    echo "✅ Cache directory exists"
    echo "Cache files: $(ls -1 .unsummarized-embeddings/*.json 2>/dev/null | wc -l)"
    echo "Total size: $(du -sh .unsummarized-embeddings 2>/dev/null | cut -f1)"
else
    echo "⚠️  Cache directory not yet created (will be created on first cache miss)"
fi
echo ""

# Test 5: Compare with load-context-semantic.py
echo "Test 5: Comparison with load-context-semantic.py"
echo "--- Unsummarized sessions (last 24hrs) ---"
python3 scripts/search-unsummarized.py "recent work" --top-k 2 2>&1 | grep -E "(Found|Query|Session)" | head -5
echo ""
echo "--- Diary (all time) ---"
python3 scripts/load-context-semantic.py "recent work" --top-k 2 2>&1 | grep -E "(Found|Query|---)" | head -5
echo ""

echo "=== Tests Complete ==="
