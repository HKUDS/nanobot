import time
from abc import ABC
from typing import Any, Optional, Union

from huggingface_hub.hf_api import InferenceProviderMapping
from huggingface_hub.inference._common import RequestParameters, _as_dict
from huggingface_hub.inference._providers._common import BaseConversationalTask, TaskProviderHelper, filter_none
from huggingface_hub.utils import get_session


_PROVIDER = "zai-org"
_BASE_URL = "https://api.z.ai"
_POLLING_INTERVAL = 5  # seconds
_MAX_POLL_ATTEMPTS = 60


class ZaiTask(TaskProviderHelper, ABC):
    def __init__(self, task: str):
        super().__init__(provider=_PROVIDER, base_url=_BASE_URL, task=task)

    def _prepare_headers(self, headers: dict, api_key: str) -> dict[str, Any]:
        headers = super()._prepare_headers(headers, api_key)
        headers["Accept-Language"] = "en-US,en"
        headers["x-source-channel"] = "hugging_face"
        return headers


class ZaiConversationalTask(BaseConversationalTask):
    def __init__(self):
        super().__init__(provider=_PROVIDER, base_url=_BASE_URL)

    def _prepare_headers(self, headers: dict, api_key: str) -> dict[str, Any]:
        headers = super()._prepare_headers(headers, api_key)
        headers["Accept-Language"] = "en-US,en"
        headers["x-source-channel"] = "hugging_face"
        return headers

    def _prepare_route(self, mapped_model: str, api_key: str) -> str:
        return "/api/paas/v4/chat/completions"


class ZaiTextToImageTask(ZaiTask):
    """Text-to-image task for ZAI provider using async API."""

    def __init__(self):
        super().__init__("text-to-image")

    def _prepare_route(self, mapped_model: str, api_key: str) -> str:
        return "/api/paas/v4/async/images/generations"

    def _prepare_payload_as_dict(
        self, inputs: Any, parameters: dict, provider_mapping_info: InferenceProviderMapping
    ) -> Optional[dict]:
        width = parameters.pop("width", None)
        height = parameters.pop("height", None)
        size = None
        if width is not None and height is not None:
            size = f"{width}x{height}"

        payload: dict[str, Any] = {
            "model": provider_mapping_info.provider_id,
            "prompt": inputs,
        }
        if size is not None:
            payload["size"] = size

        payload.update(filter_none(parameters))
        return payload

    def get_response(
        self,
        response: Union[bytes, dict],
        request_params: Optional[RequestParameters] = None,
    ) -> Any:
        """Handle async response by polling for results."""
        response_dict = _as_dict(response)

        task_id = response_dict.get("id")
        if task_id is None:
            raise ValueError("No task_id in response from ZAI API")

        task_status = response_dict.get("task_status")
        if task_status == "FAIL":
            raise ValueError(f"ZAI image generation failed for request {task_id}")

        if task_status == "PROCESSING" and request_params is not None:
            return self._poll_for_result(task_id, request_params)

        return self._extract_image(response_dict)

    def _poll_for_result(self, task_id: str, request_params: RequestParameters) -> bytes:
        """Poll the async-result endpoint until completion."""
        session = get_session()
        base_url = request_params.url.rsplit("/api/paas/v4/async/images/generations", 1)[0]
        poll_url = f"{base_url}/api/paas/v4/async-result/{task_id}"

        for _ in range(_MAX_POLL_ATTEMPTS):
            poll_response = session.get(poll_url, headers=request_params.headers)
            poll_response.raise_for_status()
            result = poll_response.json()

            task_status = result.get("task_status")
            if task_status == "SUCCESS":
                return self._extract_image(result)
            elif task_status == "FAIL":
                raise ValueError(f"Zai text-to-image generation failed for request {task_id}")

            time.sleep(_POLLING_INTERVAL)

        raise ValueError(
            f"Timed out while waiting for the result from Zai API - aborting after {_MAX_POLL_ATTEMPTS} attempts"
        )

    def _extract_image(self, result: dict) -> bytes:
        """Extract and download the image from the result."""
        image_result = result.get("image_result")
        if not image_result or not isinstance(image_result, list) or len(image_result) == 0:
            raise ValueError("No image_result in response from ZAI API")

        image_url = image_result[0].get("url")
        if not image_url:
            raise ValueError("No image URL in response from ZAI API")

        session = get_session()
        image_response = session.get(image_url)
        image_response.raise_for_status()
        return image_response.content
