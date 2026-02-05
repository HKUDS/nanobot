from ._common import BaseConversationalTask


_PROVIDER = "clarifai"
_BASE_URL = "https://api.clarifai.com"


class ClarifaiConversationalTask(BaseConversationalTask):
    def __init__(self):
        super().__init__(provider=_PROVIDER, base_url=_BASE_URL)

    def _prepare_route(self, mapped_model: str, api_key: str) -> str:
        return "/v2/ext/openai/v1/chat/completions"
