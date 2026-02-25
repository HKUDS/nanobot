from typing import Any, Optional, Union

from huggingface_hub.hf_api import InferenceProviderMapping
from huggingface_hub.inference._common import RequestParameters, _as_dict, _as_url
from huggingface_hub.inference._providers._common import TaskProviderHelper, filter_none
from huggingface_hub.utils import get_session


_PROVIDER = "replicate"
_BASE_URL = "https://api.replicate.com"


class ReplicateTask(TaskProviderHelper):
    def __init__(self, task: str):
        super().__init__(provider=_PROVIDER, base_url=_BASE_URL, task=task)

    def _prepare_headers(self, headers: dict, api_key: str) -> dict[str, Any]:
        headers = super()._prepare_headers(headers, api_key)
        headers["Prefer"] = "wait"
        return headers

    def _prepare_route(self, mapped_model: str, api_key: str) -> str:
        if ":" in mapped_model:
            return "/v1/predictions"
        return f"/v1/models/{mapped_model}/predictions"

    def _prepare_payload_as_dict(
        self, inputs: Any, parameters: dict, provider_mapping_info: InferenceProviderMapping
    ) -> Optional[dict]:
        mapped_model = provider_mapping_info.provider_id
        payload: dict[str, Any] = {"input": {"prompt": inputs, **filter_none(parameters)}}
        if ":" in mapped_model:
            version = mapped_model.split(":", 1)[1]
            payload["version"] = version
        return payload

    def get_response(self, response: Union[bytes, dict], request_params: Optional[RequestParameters] = None) -> Any:
        response_dict = _as_dict(response)
        if response_dict.get("output") is None:
            raise TimeoutError(
                f"Inference request timed out after 60 seconds. No output generated for model {response_dict.get('model')}"
                "The model might be in cold state or starting up. Please try again later."
            )
        output_url = (
            response_dict["output"] if isinstance(response_dict["output"], str) else response_dict["output"][0]
        )
        return get_session().get(output_url).content


class ReplicateTextToImageTask(ReplicateTask):
    def __init__(self):
        super().__init__("text-to-image")

    def _prepare_payload_as_dict(
        self, inputs: Any, parameters: dict, provider_mapping_info: InferenceProviderMapping
    ) -> Optional[dict]:
        payload: dict = super()._prepare_payload_as_dict(inputs, parameters, provider_mapping_info)  # type: ignore[assignment]
        if provider_mapping_info.adapter_weights_path is not None:
            payload["input"]["lora_weights"] = f"https://huggingface.co/{provider_mapping_info.hf_model_id}"
        return payload


class ReplicateTextToSpeechTask(ReplicateTask):
    def __init__(self):
        super().__init__("text-to-speech")

    def _prepare_payload_as_dict(
        self, inputs: Any, parameters: dict, provider_mapping_info: InferenceProviderMapping
    ) -> Optional[dict]:
        payload: dict = super()._prepare_payload_as_dict(inputs, parameters, provider_mapping_info)  # type: ignore[assignment]
        payload["input"]["text"] = payload["input"].pop("prompt")  # rename "prompt" to "text" for TTS
        return payload


class ReplicateAutomaticSpeechRecognitionTask(ReplicateTask):
    def __init__(self) -> None:
        super().__init__("automatic-speech-recognition")

    def _prepare_payload_as_dict(
        self,
        inputs: Any,
        parameters: dict,
        provider_mapping_info: InferenceProviderMapping,
    ) -> Optional[dict]:
        mapped_model = provider_mapping_info.provider_id
        audio_url = _as_url(inputs, default_mime_type="audio/wav")

        payload: dict[str, Any] = {
            "input": {
                **{"audio": audio_url},
                **filter_none(parameters),
            }
        }

        if ":" in mapped_model:
            payload["version"] = mapped_model.split(":", 1)[1]

        return payload

    def get_response(self, response: Union[bytes, dict], request_params: Optional[RequestParameters] = None) -> Any:
        response_dict = _as_dict(response)
        output = response_dict.get("output")

        if isinstance(output, str):
            return {"text": output}

        if isinstance(output, list) and output:
            first_item = output[0]
            if isinstance(first_item, str):
                return {"text": first_item}
            if isinstance(first_item, dict):
                output = first_item

        text: Optional[str] = None
        if isinstance(output, dict):
            transcription = output.get("transcription")
            if isinstance(transcription, str):
                text = transcription

            translation = output.get("translation")
            if isinstance(translation, str):
                text = translation

            txt_file = output.get("txt_file")
            if isinstance(txt_file, str):
                text_response = get_session().get(txt_file)
                text_response.raise_for_status()
                text = text_response.text

        if text is not None:
            return {"text": text}

        raise ValueError("Received malformed response from Replicate automatic-speech-recognition API")


class ReplicateImageToImageTask(ReplicateTask):
    def __init__(self):
        super().__init__("image-to-image")

    def _prepare_payload_as_dict(
        self, inputs: Any, parameters: dict, provider_mapping_info: InferenceProviderMapping
    ) -> Optional[dict]:
        image_url = _as_url(inputs, default_mime_type="image/jpeg")

        # Different Replicate models expect the image in different keys
        payload: dict[str, Any] = {
            "input": {
                "image": image_url,
                "images": [image_url],
                "input_image": image_url,
                "input_images": [image_url],
                **filter_none(parameters),
            }
        }

        mapped_model = provider_mapping_info.provider_id
        if ":" in mapped_model:
            version = mapped_model.split(":", 1)[1]
            payload["version"] = version
        return payload
