#!/usr/bin/env python3
"""Use OpenAI Python client against NVIDIA Integrate (example).

Prerequisites:
  pip install openai

Usage:
  python3 scripts/test_nvidia_openai_client.py
"""
import json
import os
from pathlib import Path

try:
    from openai import OpenAI
except Exception:
    raise SystemExit("Please install the OpenAI SDK: pip install openai")


def load_config_key():
    cfg = Path.home() / ".nanobot" / "config.json"
    if cfg.exists():
        data = json.loads(cfg.read_text())
        key = data.get("providers", {}).get("nvidia", {}).get("apiKey")
        base = data.get("providers", {}).get("nvidia", {}).get("apiBase")
        model = data.get("agents", {}).get("defaults", {}).get("model")
        return key, base, model
    return None, None, None


def main():
    api_key = os.environ.get("NVIDIA_API_KEY")
    api_base = os.environ.get("NVIDIA_API_BASE")
    model = os.environ.get("NVIDIA_MODEL")

    k, b, m = load_config_key()
    api_key = api_key or k
    api_base = api_base or b or "https://integrate.api.nvidia.com/v1"
    model = model or m or "nvidia/nemotron-3-nano-30b-a3b"

    if not api_key:
        raise SystemExit("No NVIDIA API key found. Set NVIDIA_API_KEY or ~/.nanobot/config.json")

    client = OpenAI(base_url=api_base, api_key=api_key)

    print("Model:", model)
    print("API base:", api_base)

    # Non-streaming example
    print("\n== Non-streaming test ==")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Ping — reply with 'pong'"}],
        max_tokens=64,
        temperature=0.0,
    )
    # resp is pydantic model-like; read attributes safely
    resp_id = getattr(resp, "id", None) or getattr(resp, "_data", {}).get("id") if hasattr(resp, "_data") else None
    choices = getattr(resp, "choices", None) or (getattr(resp, "_data", {}).get("choices") if hasattr(resp, "_data") else None)
    print("id:", resp_id)
    print("choices:", choices)

    # Streaming example (iterable of chunks)
    print("\n== Streaming test == (press Ctrl+C to stop) ==")
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Stream test. Reply 'pong' and stream reasoning."}],
        max_tokens=256,
        temperature=0.0,
        stream=True,
    )

    try:
        for chunk in stream:
            # chunk is likely a dict-like object; be tolerant with attributes
            if not getattr(chunk, "choices", None):
                # some SDKs return dicts
                j = dict(chunk)
                chs = j.get("choices")
            else:
                chs = chunk.choices

            if not chs:
                continue

            c0 = chs[0]
            # print reasoning if present
            reasoning = getattr(c0.delta, "reasoning_content", None) if hasattr(c0, "delta") else None
            if reasoning:
                print(reasoning, end="", flush=True)

            # print content if present
            content = None
            if hasattr(c0, "delta") and getattr(c0.delta, "content", None) is not None:
                content = c0.delta.content
            elif isinstance(c0, dict) and c0.get("delta") and c0["delta"].get("content"):
                content = c0["delta"]["content"]

            if content:
                print(content, end="", flush=True)
    except KeyboardInterrupt:
        print("\nStream stopped by user")


if __name__ == "__main__":
    main()
