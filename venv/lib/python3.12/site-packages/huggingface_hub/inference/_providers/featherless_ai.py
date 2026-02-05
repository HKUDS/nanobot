from typing import Any, Optional, Union

from huggingface_hub.hf_api import InferenceProviderMapping
from huggingface_hub.inference._common import RequestParameters, _as_dict

from ._common import BaseConversationalTask, BaseTextGenerationTask, filter_none


_PROVIDER = "featherless-ai"
_BASE_URL = "https://api.featherless.ai"


class FeatherlessTextGenerationTask(BaseTextGenerationTask):
    def __init__(self):
        super().__init__(provider=_PROVIDER, base_url=_BASE_URL)

    def _prepare_payload_as_dict(
        self, inputs: Any, parameters: dict, provider_mapping_info: InferenceProviderMapping
    ) -> Optional[dict]:
        params = filter_none(parameters.copy())
        params["max_tokens"] = params.pop("max_new_tokens", None)

        return {"prompt": inputs, **params, "model": provider_mapping_info.provider_id}

    def get_response(self, response: Union[bytes, dict], request_params: Optional[RequestParameters] = None) -> Any:
        output = _as_dict(response)["choices"][0]
        return {
            "generated_text": output["text"],
            "details": {
                "finish_reason": output.get("finish_reason"),
                "seed": output.get("seed"),
            },
        }


class FeatherlessConversationalTask(BaseConversationalTask):
    def __init__(self):
        super().__init__(provider=_PROVIDER, base_url=_BASE_URL)
