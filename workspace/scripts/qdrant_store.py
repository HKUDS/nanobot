#!/usr/bin/env python3
"""Store text in local Qdrant with Mistral embeddings.
Usage:
  ./qdrant_store.py "text" [collection]
Env:
  MISTRAL_API_KEY (required)
  MISTRAL_API_BASE (default: https://api.mistral.ai/v1)
  QDRANT_URL (default: http://localhost:6333)
"""

import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, UTC


def post_json(url: str, payload: dict, headers: dict | None = None, method: str = "POST") -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def ensure_collection(qdrant_url: str, name: str, size: int = 1024) -> None:
    try:
        urllib.request.urlopen(f"{qdrant_url}/collections/{name}", timeout=5)
        return
    except Exception:
        pass
    post_json(
        f"{qdrant_url}/collections/{name}",
        {"vectors": {"size": size, "distance": "Cosine"}},
        method="PUT",
    )


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "text is required"}))
        return 1

    text = sys.argv[1]
    collection = sys.argv[2] if len(sys.argv) > 2 else "nanobot-memory"

    mistral_key = os.getenv("MISTRAL_API_KEY", "")
    if not mistral_key:
        print(json.dumps({"error": "MISTRAL_API_KEY is required"}))
        return 1

    mistral_api_base = os.getenv("MISTRAL_API_BASE", "https://api.mistral.ai/v1")
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")

    emb = post_json(
        f"{mistral_api_base}/embeddings",
        {"model": "mistral-embed", "input": text},
        headers={"Authorization": f"Bearer {mistral_key}"},
    )
    vector = emb["data"][0]["embedding"]

    ensure_collection(qdrant_url, collection, size=len(vector))

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    point_id = hashlib.md5(f"{text}|{ts}".encode()).hexdigest()

    result = post_json(
        f"{qdrant_url}/collections/{collection}/points",
        {
            "points": [
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": {"text": text, "timestamp": ts},
                }
            ]
        },
        method="PUT",
    )

    print(json.dumps({"ok": True, "collection": collection, "point_id": point_id, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
