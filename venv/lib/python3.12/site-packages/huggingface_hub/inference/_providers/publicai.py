from ._common import BaseConversationalTask


class PublicAIConversationalTask(BaseConversationalTask):
    def __init__(self):
        super().__init__(provider="publicai", base_url="https://api.publicai.co")
