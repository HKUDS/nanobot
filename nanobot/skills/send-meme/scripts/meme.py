#!/usr/bin/env python3
"""Meme manager for nanobot - search, fetch, download, and manage memes."""

import sys
import os
import json
import random
import hashlib
import urllib.request
import urllib.parse
from pathlib import Path

MEME_DIR = Path.home() / ".nanobot" / "media" / "memes"
TAGS_FILE = MEME_DIR / ".tags.json"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# Online meme API endpoints (free, no key required)
MEME_APIS = [
    # meme-api.com - Reddit memes (reliable, no key needed)
    {
        "name": "meme-api",
        "url": "https://meme-api.com/gimme",
        "type": "json",
        "image_key": "url",
        "subreddits": {
            "default": ["memes", "me_irl", "wholesomememes"],
            "funny": ["funny", "memes"],
            "cat": ["catmemes", "CatsBeingCats"],
            "dog": ["rarepuppers"],
            "anime": ["anime_irl", "Animemes"],
        },
    },
    # imgflip - meme templates
    {
        "name": "imgflip",
        "url": "https://api.imgflip.com/get_memes",
        "type": "json",
    },
]


def init():
    """Create meme directory if not exists."""
    MEME_DIR.mkdir(parents=True, exist_ok=True)


def load_tags() -> dict:
    """Load tags from file."""
    if TAGS_FILE.exists():
        try:
            return json.loads(TAGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_tags(tags: dict):
    """Save tags to file."""
    init()
    TAGS_FILE.write_text(json.dumps(tags, ensure_ascii=False, indent=2), encoding="utf-8")


def get_local_memes(keyword: str | None = None) -> list[str]:
    """List local memes, optionally filtered by keyword."""
    init()
    tags = load_tags()
    memes = []
    for f in sorted(MEME_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
            if keyword is None:
                memes.append(str(f))
            else:
                kw = keyword.lower()
                # Match against filename
                if kw in f.stem.lower():
                    memes.append(str(f))
                    continue
                # Match against tags
                file_tags = tags.get(f.name, [])
                if any(kw in t.lower() for t in file_tags):
                    memes.append(str(f))
    return memes


def download_image(url: str, name: str | None = None) -> str | None:
    """Download an image from URL to local meme collection."""
    init()
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "image/*,*/*",
        })
        resp = urllib.request.urlopen(req, timeout=15)
        data = resp.read()

        content_type = resp.headers.get("Content-Type", "")

        # Determine extension
        ext = ".jpg"  # default
        if "png" in content_type:
            ext = ".png"
        elif "gif" in content_type:
            ext = ".gif"
        elif "webp" in content_type:
            ext = ".webp"
        elif "bmp" in content_type:
            ext = ".bmp"
        else:
            # Try from URL path
            url_path = urllib.parse.urlparse(url).path
            url_ext = os.path.splitext(url_path)[1].lower()
            if url_ext in IMAGE_EXTS:
                ext = url_ext

        if name is None:
            name = hashlib.md5(data).hexdigest()[:12]

        # Remove extension from name if already has one
        name_path = Path(name)
        if name_path.suffix.lower() in IMAGE_EXTS:
            name = name_path.stem
            ext = name_path.suffix

        filepath = MEME_DIR / f"{name}{ext}"
        filepath.write_bytes(data)
        return str(filepath)
    except Exception as e:
        print(f"Error downloading: {e}", file=sys.stderr)
        return None


def fetch_from_meme_api(keyword: str | None = None) -> str | None:
    """Fetch a meme from meme-api.com (Reddit memes)."""
    init()
    api = MEME_APIS[0]  # meme-api

    # Pick subreddit based on keyword
    subreddit = None
    if keyword:
        kw = keyword.lower()
        subs = api.get("subreddits", {})
        for key, sub_list in subs.items():
            if key != "default" and kw in key:
                subreddit = random.choice(sub_list)
                break
        if not subreddit:
            subreddit = random.choice(subs.get("default", ["memes"]))
    else:
        subreddit = random.choice(api["subreddits"]["default"])

    url = f"{api['url']}/{subreddit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode("utf-8"))
        img_url = result.get("url")
        if img_url:
            title = result.get("title", "")
            dl_name = hashlib.md5(img_url.encode()).hexdigest()[:12]
            if keyword:
                dl_name = f"{keyword}_{dl_name}"
            return download_image(img_url, dl_name)
    except Exception as e:
        print(f"meme-api failed: {e}", file=sys.stderr)
    return None


def fetch_from_imgflip() -> str | None:
    """Fetch a random meme template from imgflip."""
    init()
    try:
        req = urllib.request.Request(
            "https://api.imgflip.com/get_memes",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode("utf-8"))
        memes = result.get("data", {}).get("memes", [])
        if memes:
            meme = random.choice(memes[:50])  # Top 50 popular memes
            img_url = meme.get("url")
            name = meme.get("name", "").replace(" ", "_")[:30]
            if img_url:
                return download_image(img_url, name or None)
    except Exception as e:
        print(f"imgflip failed: {e}", file=sys.stderr)
    return None


def fetch_from_api(keyword: str | None = None) -> str | None:
    """Fetch a meme from online APIs. Tries multiple sources."""
    init()

    # Try meme-api first (more variety)
    result = fetch_from_meme_api(keyword)
    if result:
        return result

    # Fallback to imgflip
    result = fetch_from_imgflip()
    if result:
        return result

    return None


def cmd_search(keyword: str):
    """Search for memes by keyword (local first, then online)."""
    results = get_local_memes(keyword)
    if results:
        print(json.dumps(results, ensure_ascii=False))
    else:
        # Try online
        result = fetch_from_api(keyword)
        if result:
            print(json.dumps([result], ensure_ascii=False))
        else:
            print(json.dumps([], ensure_ascii=False))


def cmd_random():
    """Get a random meme."""
    memes = get_local_memes()
    if memes:
        print(random.choice(memes))
    else:
        result = fetch_from_api()
        if result:
            print(result)
        else:
            print("ERROR: No memes available. Add memes to ~/.nanobot/media/memes/ or check network.", file=sys.stderr)
            sys.exit(1)


def cmd_fetch(keyword: str | None = None):
    """Fetch a meme from online API."""
    result = fetch_from_api(keyword)
    if result:
        print(result)
    else:
        print("ERROR: Failed to fetch meme from online APIs.", file=sys.stderr)
        sys.exit(1)


def cmd_download(url: str, name: str | None = None):
    """Download a meme from URL."""
    result = download_image(url, name)
    if result:
        print(result)
    else:
        print("ERROR: Failed to download image.", file=sys.stderr)
        sys.exit(1)


def cmd_list(keyword: str | None = None):
    """List local memes."""
    memes = get_local_memes(keyword)
    if memes:
        print(json.dumps(memes, ensure_ascii=False, indent=2))
    else:
        if keyword:
            print(f"No memes matching '{keyword}' found locally.")
        else:
            print("No memes found. Add images to ~/.nanobot/media/memes/")


def cmd_tag(filepath: str, tags: list[str]):
    """Tag a meme file."""
    p = Path(filepath)
    if not p.exists():
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    all_tags = load_tags()
    existing = all_tags.get(p.name, [])
    merged = list(set(existing + tags))
    all_tags[p.name] = merged
    save_tags(all_tags)
    print(f"Tags for {p.name}: {', '.join(merged)}")


def cmd_tags(filepath: str):
    """Show tags for a meme file."""
    p = Path(filepath)
    all_tags = load_tags()
    file_tags = all_tags.get(p.name, [])
    if file_tags:
        print(f"Tags for {p.name}: {', '.join(file_tags)}")
    else:
        print(f"No tags for {p.name}")


def main():
    if len(sys.argv) < 2:
        print("Usage: meme.py <command> [args...]")
        print("Commands: search, random, fetch, download, list, tag, tags")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: meme.py search <keyword>", file=sys.stderr)
            sys.exit(1)
        cmd_search(sys.argv[2])

    elif cmd == "random":
        cmd_random()

    elif cmd == "fetch":
        keyword = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_fetch(keyword)

    elif cmd == "download":
        if len(sys.argv) < 3:
            print("Usage: meme.py download <url> [name]", file=sys.stderr)
            sys.exit(1)
        name = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_download(sys.argv[2], name)

    elif cmd == "list":
        keyword = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_list(keyword)

    elif cmd == "tag":
        if len(sys.argv) < 4:
            print("Usage: meme.py tag <filepath> <tag1> [tag2] ...", file=sys.stderr)
            sys.exit(1)
        cmd_tag(sys.argv[2], sys.argv[3:])

    elif cmd == "tags":
        if len(sys.argv) < 3:
            print("Usage: meme.py tags <filepath>", file=sys.stderr)
            sys.exit(1)
        cmd_tags(sys.argv[2])

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Commands: search, random, fetch, download, list, tag, tags")
        sys.exit(1)


if __name__ == "__main__":
    main()
