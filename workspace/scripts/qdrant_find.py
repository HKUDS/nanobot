#!/usr/bin/env python3
"""Semantic search in local Qdrant using Mistral embeddings.
Usage:
  ./qdrant_find.py "query" [collection] [limit]
Env:
  MISTRAL_API_KEY (required)
  MISTRAL_API_BASE (default: https://api.mistral.ai/v1)
  QDRANT_URL (default: http://localhost:6333)
"""

import json
import os
import sys
import urllib.request


def post_json(url: str, payload: dict, headers: dict | None = None, method: str = "POST") -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "query is required"}))
        return 1

    query = sys.argv[1]
    collection = sys.argv[2] if len(sys.argv) > 2 else "nanobot-memory"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    mistral_key = os.getenv("MISTRAL_API_KEY", "")
    if not mistral_key:
        print(json.dumps({"error": "MISTRAL_API_KEY is required"}))
        return 1

    mistral_api_base = os.getenv("MISTRAL_API_BASE", "https://api.mistral.ai/v1")
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")

    emb = post_json(
        f"{mistral_api_base}/embeddings",
        {"model": "mistral-embed", "input": query},
        headers={"Authorization": f"Bearer {mistral_key}"},
    )
    vector = emb["data"][0]["embedding"]

    res = post_json(
        f"{qdrant_url}/collections/{collection}/points/search",
        {
            "vector": vector,
            "limit": limit,
            "with_payload": True,
        },
    )

    print(json.dumps({"ok": True, "collection": collection, "query": query, "result": res.get("result", [])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
