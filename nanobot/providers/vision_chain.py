"""Vision description pipeline: HF Qwen3-VL → OpenRouter Qwen3-VL → Anthropic Sonnet.

Accepts either file paths or pre-encoded base64 image data (from image_url blocks).
Returns a plain-text description in Italian, suitable for injecting into agent context.
"""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
import urllib.request
from pathlib import Path

from loguru import logger

def _get_api_key(provider: str, env_var: str) -> str:
    """Read API key: env var first, then ~/.nanobot/config.json, then empty string."""
    val = os.environ.get(env_var, "")
    if val and not val.startswith("${"):
        return val
    try:
        import json
        cfg = json.load(open(os.path.expanduser("~/.nanobot/config.json")))
        raw = cfg.get("providers", {}).get(provider, {}).get("apiKey", "")
        if raw and not raw.startswith("${"):
            return raw
        # template like ${SOME_VAR} — resolve from env
        if raw.startswith("${") and raw.endswith("}"):
            return os.environ.get(raw[2:-1], "")
    except Exception:
        pass
    return ""


_PROMPT = (
    "Descrivi il contenuto di quest'immagine in italiano in modo conciso (2-4 frasi). "
    "Focalizzati su elementi visivamente rilevanti: oggetti, testo leggibile, "
    "stato o condizione di eventuali prodotti, persone o ambienti presenti."
)

# ---------------------------------------------------------------------------
# Internal HTTP helpers
# ---------------------------------------------------------------------------

def _urlopen(req: urllib.request.Request, timeout: int = 30) -> bytes:
    return urllib.request.urlopen(req, timeout=timeout).read()


async def _async_urlopen(req: urllib.request.Request, timeout: int = 30) -> bytes:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _urlopen(req, timeout))


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------

def _load_image_part(source: str) -> dict | None:
    """Return an OpenAI image_url block from a file path or an existing data-URL."""
    if source.startswith("data:image/"):
        return {"type": "image_url", "image_url": {"url": source}}
    p = Path(source)
    if not p.is_file():
        return None
    raw = p.read_bytes()
    mime = _detect_mime(raw) or mimetypes.guess_type(source)[0]
    if not mime or not mime.startswith("image/"):
        return None
    b64 = base64.b64encode(raw).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _detect_mime(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------

async def _openai_compat(
    base_url: str, api_key: str, model: str, image_parts: list[dict]
) -> str | None:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": image_parts + [{"type": "text", "text": _PROMPT}],
            }
        ],
        "max_tokens": 400,
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        data = json.loads(await _async_urlopen(req, timeout=40))
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        return text or None
    except Exception as e:
        logger.debug("vision_chain openai_compat {} failed: {}", base_url, e)
        return None


async def _anthropic(api_key: str, image_parts: list[dict]) -> str | None:
    anthropic_content = []
    for part in image_parts:
        url_val = (part.get("image_url") or {}).get("url", "")
        m = re.match(r"data:(image/\w+);base64,(.+)", url_val, re.DOTALL)
        if m:
            anthropic_content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)},
            })
    anthropic_content.append({"type": "text", "text": _PROMPT})
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 400,
        "messages": [{"role": "user", "content": anthropic_content}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    try:
        data = json.loads(await _async_urlopen(req, timeout=40))
        blocks = data.get("content") or []
        text = next((b.get("text", "").strip() for b in blocks if b.get("type") == "text"), None)
        return text or None
    except Exception as e:
        logger.debug("vision_chain anthropic failed: {}", e)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def describe_images(sources: list[str]) -> str:
    """Describe one or more images. *sources* may be file paths or data-URLs.

    Tries providers in order: HF Qwen3-VL → OpenRouter Qwen3-VL → Anthropic Sonnet.
    Returns an empty string if all providers fail or no valid images found.
    """
    image_parts = [p for s in sources if (p := _load_image_part(s)) is not None]
    if not image_parts:
        return ""

    # 1. HuggingFace Qwen3-VL-30B
    hf_key = _get_api_key("huggingface", "HF_TOKEN")
    if hf_key:
        result = await _openai_compat(
            "https://router.huggingface.co/v1",
            hf_key,
            "Qwen/Qwen3-VL-30B-A3B-Instruct",
            image_parts,
        )
        if result:
            logger.debug("vision_chain: described via HF Qwen3-VL")
            return result

    # 2. OpenRouter — try google/gemini-flash-1.5 (vision, low cost) as fallback
    or_key = _get_api_key("openrouter", "OPENROUTER_API_KEY")
    if or_key:
        result = await _openai_compat(
            "https://openrouter.ai/api/v1",
            or_key,
            "google/gemini-flash-1.5",
            image_parts,
        )
        if result:
            logger.debug("vision_chain: described via OpenRouter Gemini Flash")
            return result

    # 3. Anthropic Claude Sonnet (last resort)
    ant_key = _get_api_key("anthropic", "ANTHROPIC_API_KEY")
    if ant_key:
        result = await _anthropic(ant_key, image_parts)
        if result:
            logger.debug("vision_chain: described via Anthropic Sonnet")
            return result

    logger.warning("vision_chain: all providers failed for {} image(s)", len(image_parts))
    return ""
