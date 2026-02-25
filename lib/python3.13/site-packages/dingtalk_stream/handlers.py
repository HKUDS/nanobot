from .frames import Headers
from .frames import AckMessage
from .frames import SystemMessage
from .frames import EventMessage
from .frames import CallbackMessage
from .log import setup_default_logger

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .stream import DingTalkStreamClient

class CallbackHandler(object):
    TOPIC_CARD_CALLBACK = '/v1.0/card/instances/callback'

    def __init__(self):
        self.dingtalk_client: 'DingTalkStreamClient' = None
        self.logger = setup_default_logger('dingtalk_stream.handler')

    def pre_start(self):
        return

    async def process(self, message: CallbackMessage):
        return AckMessage.STATUS_NOT_IMPLEMENT, 'not implement'

    async def raw_process(self, callback_message: CallbackMessage):
        code, message = await self.process(callback_message)
        ack_message = AckMessage()
        ack_message.code = code
        ack_message.headers.message_id = callback_message.headers.message_id
        ack_message.headers.content_type = Headers.CONTENT_TYPE_APPLICATION_JSON
        ack_message.data = {"response": message}
        return ack_message


class EventHandler(object):
    def __init__(self):
        self.dingtalk_client: 'DingTalkStreamClient' = None
        self.logger = setup_default_logger('dingtalk_stream.handler')

    def pre_start(self):
        return

    async def process(self, event: EventMessage):
        return AckMessage.STATUS_NOT_IMPLEMENT, 'not implement'

    async def raw_process(self, event_message: EventMessage):
        code, message = await self.process(event_message)
        ack_message = AckMessage()
        ack_message.code = code
        ack_message.headers.message_id = event_message.headers.message_id
        ack_message.headers.content_type = Headers.CONTENT_TYPE_APPLICATION_JSON
        ack_message.message = message
        ack_message.data = event_message.data
        return ack_message


class SystemHandler(object):
    def __init__(self):
        self.dingtalk_client: 'DingTalkStreamClient' = None
        self.logger = setup_default_logger('dingtalk_stream.handler')

    def pre_start(self):
        return

    async def process(self, message: SystemMessage):
        return AckMessage.STATUS_OK, 'OK'

    async def raw_process(self, system_message: SystemMessage):
        code, message = await self.process(system_message)
        ack_message = AckMessage()
        ack_message.code = code
        ack_message.headers.message_id = system_message.headers.message_id
        ack_message.headers.content_type = Headers.CONTENT_TYPE_APPLICATION_JSON
        ack_message.message = message
        ack_message.data = system_message.data
        return ack_message
