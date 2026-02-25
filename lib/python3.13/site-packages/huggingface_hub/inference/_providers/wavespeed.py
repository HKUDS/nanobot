import base64
import time
from abc import ABC
from typing import Any, Optional, Union
from urllib.parse import urlparse

from huggingface_hub.hf_api import InferenceProviderMapping
from huggingface_hub.inference._common import RequestParameters, _as_dict
from huggingface_hub.inference._providers._common import TaskProviderHelper, filter_none
from huggingface_hub.utils import get_session, hf_raise_for_status
from huggingface_hub.utils.logging import get_logger


logger = get_logger(__name__)

# Polling interval (in seconds)
_POLLING_INTERVAL = 0.5


class WavespeedAITask(TaskProviderHelper, ABC):
    def __init__(self, task: str):
        super().__init__(provider="wavespeed", base_url="https://api.wavespeed.ai", task=task)

    def _prepare_route(self, mapped_model: str, api_key: str) -> str:
        return f"/api/v3/{mapped_model}"

    def get_response(
        self,
        response: Union[bytes, dict],
        request_params: Optional[RequestParameters] = None,
    ) -> Any:
        response_dict = _as_dict(response)
        data = response_dict.get("data", {})
        result_path = data.get("urls", {}).get("get")

        if not result_path:
            raise ValueError("No result URL found in the response")
        if request_params is None:
            raise ValueError("A `RequestParameters` object should be provided to get responses with WaveSpeed AI.")

        # Parse the request URL to determine base URL
        parsed_url = urlparse(request_params.url)
        # Add /wavespeed to base URL if going through HF router
        if parsed_url.netloc == "router.huggingface.co":
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}/wavespeed"
        else:
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        # Extract path from result_path URL
        if isinstance(result_path, str):
            result_url_path = urlparse(result_path).path
        else:
            result_url_path = result_path

        result_url = f"{base_url}{result_url_path}"

        logger.info("Processing request, polling for results...")

        # Poll until task is completed
        while True:
            time.sleep(_POLLING_INTERVAL)
            result_response = get_session().get(result_url, headers=request_params.headers)
            hf_raise_for_status(result_response)

            result = result_response.json()
            task_result = result.get("data", {})
            status = task_result.get("status")

            if status == "completed":
                # Get content from the first output URL
                if not task_result.get("outputs") or len(task_result["outputs"]) == 0:
                    raise ValueError("No output URL in completed response")

                output_url = task_result["outputs"][0]
                return get_session().get(output_url).content
            elif status == "failed":
                error_msg = task_result.get("error", "Task failed with no specific error message")
                raise ValueError(f"WaveSpeed AI task failed: {error_msg}")
            elif status in ["processing", "created"]:
                continue
            else:
                raise ValueError(f"Unknown status: {status}")


class WavespeedAITextToImageTask(WavespeedAITask):
    def __init__(self):
        super().__init__("text-to-image")

    def _prepare_payload_as_dict(
        self,
        inputs: Any,
        parameters: dict,
        provider_mapping_info: InferenceProviderMapping,
    ) -> Optional[dict]:
        return {"prompt": inputs, **filter_none(parameters)}


class WavespeedAITextToVideoTask(WavespeedAITextToImageTask):
    def __init__(self):
        WavespeedAITask.__init__(self, "text-to-video")


class WavespeedAIImageToImageTask(WavespeedAITask):
    def __init__(self):
        super().__init__("image-to-image")

    def _prepare_payload_as_dict(
        self,
        inputs: Any,
        parameters: dict,
        provider_mapping_info: InferenceProviderMapping,
    ) -> Optional[dict]:
        # Convert inputs to image (URL or base64)
        if isinstance(inputs, str) and inputs.startswith(("http://", "https://")):
            image = inputs
        elif isinstance(inputs, str):
            # If input is a file path, read it first
            with open(inputs, "rb") as f:
                file_content = f.read()
            image_b64 = base64.b64encode(file_content).decode("utf-8")
            image = f"data:image/jpeg;base64,{image_b64}"
        else:
            # If input is binary data
            image_b64 = base64.b64encode(inputs).decode("utf-8")
            image = f"data:image/jpeg;base64,{image_b64}"

        # Extract prompt from parameters if present
        prompt = parameters.pop("prompt", None)
        payload = {"image": image, **filter_none(parameters)}
        if prompt is not None:
            payload["prompt"] = prompt

        return payload


class WavespeedAIImageToVideoTask(WavespeedAIImageToImageTask):
    def __init__(self):
        WavespeedAITask.__init__(self, "image-to-video")
