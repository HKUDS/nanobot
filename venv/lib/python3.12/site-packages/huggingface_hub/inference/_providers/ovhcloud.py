from huggingface_hub.inference._providers._common import BaseConversationalTask


_PROVIDER = "ovhcloud"
_BASE_URL = "https://oai.endpoints.kepler.ai.cloud.ovh.net"


class OVHcloudConversationalTask(BaseConversationalTask):
    def __init__(self):
        super().__init__(provider=_PROVIDER, base_url=_BASE_URL)
