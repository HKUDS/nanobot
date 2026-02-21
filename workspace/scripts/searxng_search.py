#!/usr/bin/env python3
"""Search via local SearXNG instance.
Usage:
  ./searxng_search.py "query" [limit]
"""

import json
import sys
import urllib.parse
import urllib.request


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "query is required"}))
        return 1

    query = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    params = {
        "q": query,
        "format": "json",
        "language": "all",
        "pageno": 1,
        "safesearch": 0,
    }

    url = f"http://localhost:8080/search?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            data["results"] = (data.get("results") or [])[:limit]
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
