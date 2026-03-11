from typing import Optional
from httpx import AsyncClient


class NvidiaEscalateTool:
    name = 'nvidia_escalate'
    description = (
        'Escalate complex tasks to NVIDIA hosted large language models via the NVIDIA API. '
        'Use only when the task exceeds local model capability — architecture critique, '
        'independent validation, or second opinions on important decisions. '
        'Not for routine queries.'
    )

    def __init__(self, api_key: str = '', default_model: str = 'nvidia/llama-3.1-nemotron-ultra-253b-v1'):
        self.api_key = api_key
        self.default_model = default_model

    async def execute(self, prompt: str, model: Optional[str] = None) -> str:
        if not self.api_key:
            return "Error: nvidia.api_key not set in config.json"
        model = model or self.default_model
        url = 'https://integrate.api.nvidia.com/v1/chat/completions'

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': 1000,
            'temperature': 0.7,
            'stream': False,
        }

        async with AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
