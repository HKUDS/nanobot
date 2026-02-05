#!/usr/bin/env python3
import asyncio
import time
import json
from nanobot.config.loader import load_config
from nanobot.providers.litellm_provider import LiteLLMProvider


async def run_tests():
    config = load_config()
    api_key = config.providers.nvidia.api_key or config.get_api_key()
    api_base = config.providers.nvidia.api_base or config.get_api_base()
    model = config.agents.defaults.model

    print('Model config:', model)
    print('API base:', api_base)
    print('API key present:', bool(api_key))

    prov = LiteLLMProvider(api_key=api_key, api_base=api_base, default_model=model)

    tests = [
        {"label": "ping", "messages": [{"role":"user","content":"pong? reply 'pong'"}]},
        {"label": "identify", "messages": [{"role":"user","content":"Please identify the model you are running (name/version) in one short sentence."}]},
        {"label": "math_check", "messages": [{"role":"user","content":"Compute 12345 + 67890 and return only the integer result."}]}
    ]

    results = []
    for t in tests:
        start = time.time()
        resp = await prov.chat(messages=t['messages'], model=model, max_tokens=200, temperature=0.0)
        elapsed = time.time() - start
        results.append({
            'label': t['label'],
            'content': resp.content,
            'finish_reason': resp.finish_reason,
            'usage': resp.usage,
            'elapsed_s': round(elapsed,3)
        })

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(run_tests())
