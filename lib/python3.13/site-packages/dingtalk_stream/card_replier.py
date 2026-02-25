# -*- coding:utf-8 -*-
import json
import uuid

import copy
import hashlib
import platform
import requests
import aiohttp

from .utils import DINGTALK_OPENAPI_ENDPOINT
from .log import setup_default_logger
from enum import Enum, unique

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chatbot import ChatbotMessage
    from .stream import DingTalkStreamClient


class CardReplier(object):

    def __init__(
        self,
        dingtalk_client: "DingTalkStreamClient",
        incoming_message: "ChatbotMessage",
    ):
        self.dingtalk_client: "DingTalkStreamClient" = dingtalk_client
        self.incoming_message: "ChatbotMessage" = incoming_message
        self.logger = setup_default_logger("dingtalk_stream.card_replier")

    @staticmethod
    def gen_card_id(msg: "ChatbotMessage"):
        factor = "%s_%s_%s_%s_%s" % (
            msg.sender_id,
            msg.sender_corp_id,
            msg.conversation_id,
            msg.message_id,
            str(uuid.uuid1()),
        )
        m = hashlib.sha256()
        m.update(factor.encode("utf-8"))
        return m.hexdigest()

    @staticmethod
    def get_request_header(access_token):
        return {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "x-acs-dingtalk-access-token": access_token,
            "User-Agent": (
                "DingTalkStream/1.0 SDK/0.1.0 Python/%s "
                "(+https://github.com/open-dingtalk/dingtalk-stream-sdk-python)"
            )
            % platform.python_version(),
        }

    def create_and_send_card(
        self,
        card_template_id: str,
        card_data: dict,
        callback_type: str = "STREAM",
        callback_route_key: str = "",
        at_sender: bool = False,
        at_all: bool = False,
        recipients: list = None,
        support_forward: bool = True,
    ) -> str:
        """
        发送卡片，两步骤：创建+投放。
        https://open.dingtalk.com/document/orgapp/interface-for-creating-a-card-instance
        :param support_forward: 卡片是否支持转发
        :param callback_route_key: HTTP 回调时的 route key
        :param callback_type: 卡片回调模式
        :param recipients: 接收者
        :param card_template_id: 卡片模板 ID
        :param card_data: 卡片数据
        :param at_sender: 是否@发送者
        :param at_all: 是否@所有人
        :return: 卡片的实例ID
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error(
                "CardResponder.send_card failed, cannot get dingtalk access token"
            )
            return ""

        card_instance_id = self.gen_card_id(self.incoming_message)
        body = {
            "cardTemplateId": card_template_id,
            "outTrackId": card_instance_id,
            "cardData": {"cardParamMap": card_data},
            "callbackType": callback_type,
            "imGroupOpenSpaceModel": {"supportForward": support_forward},
            "imRobotOpenSpaceModel": {"supportForward": support_forward},
        }

        if callback_type == "HTTP":
            body["callbackType"] = "HTTP"
            body["callbackRouteKey"] = callback_route_key

        # 创建卡片实例。https://open.dingtalk.com/document/orgapp/interface-for-creating-a-card-instance
        url = DINGTALK_OPENAPI_ENDPOINT + "/v1.0/card/instances"
        try:
            response_text = ""
            response = requests.post(
                url, headers=self.get_request_header(access_token), json=body
            )
            response_text = response.text
            
            response.raise_for_status()
        except Exception as e:
            self.logger.error(
                f"CardReplier.create_and_send_card failed, create card instance failed, error={e}, response.text={response_text}"
            )
            return ""

        body = {"outTrackId": card_instance_id, "userIdType": 1}

        # 2：群聊，1：单聊
        if self.incoming_message.conversation_type == "2":
            body["openSpaceId"] = "dtv1.card//{spaceType}.{spaceId}".format(
                spaceType="IM_GROUP", spaceId=self.incoming_message.conversation_id
            )
            body["imGroupOpenDeliverModel"] = {
                "robotCode": self.dingtalk_client.credential.client_id,
            }

            if at_all:
                body["imGroupOpenDeliverModel"]["atUserIds"] = {
                    "@ALL": "@ALL",
                }
            elif at_sender:
                body["imGroupOpenDeliverModel"]["atUserIds"] = {
                    self.incoming_message.sender_staff_id: self.incoming_message.sender_nick,
                }

            if recipients is not None:
                body["imGroupOpenDeliverModel"]["recipients"] = recipients

            # 增加托管extension
            if self.incoming_message.hosting_context is not None:
                body["imGroupOpenDeliverModel"]["extension"] = {
                    "hostingRepliedContext": json.dumps(
                        {"userId": self.incoming_message.hosting_context.user_id}
                    )
                }
        elif self.incoming_message.conversation_type == "1":
            body["openSpaceId"] = "dtv1.card//{spaceType}.{spaceId}".format(
                spaceType="IM_ROBOT", spaceId=self.incoming_message.sender_staff_id
            )
            body["imRobotOpenDeliverModel"] = {"spaceType": "IM_ROBOT"}

            # 增加托管extension
            if self.incoming_message.hosting_context is not None:
                body["imRobotOpenDeliverModel"]["extension"] = {
                    "hostingRepliedContext": json.dumps(
                        {"userId": self.incoming_message.hosting_context.user_id}
                    )
                }

        # 投放卡片。https://open.dingtalk.com/document/orgapp/delivery-card-interface
        url = DINGTALK_OPENAPI_ENDPOINT + "/v1.0/card/instances/deliver"
        try:
            response_text = ""
            response = requests.post(
                url, headers=self.get_request_header(access_token), json=body
            )
            response_text = response.text
            
            response.raise_for_status()
            
            return card_instance_id
        except Exception as e:
            self.logger.error(
                f"CardReplier.create_and_send_card failed, send card failed, error={e}, response.text={response_text}"
            )
            return ""

    async def async_create_and_send_card(
        self,
        card_template_id: str,
        card_data: dict,
        callback_type: str = "STREAM",
        callback_route_key: str = "",
        at_sender: bool = False,
        at_all: bool = False,
        recipients: list = None,
        support_forward: bool = True,
    ) -> str:
        """
        发送卡片，两步骤：创建+投放。
        https://open.dingtalk.com/document/orgapp/interface-for-creating-a-card-instance
        :param support_forward: 卡片是否支持转发
        :param callback_route_key: HTTP 回调时的 route key
        :param callback_type: 卡片回调模式
        :param recipients: 接收者
        :param card_template_id: 卡片模板 ID
        :param card_data: 卡片数据
        :param at_sender: 是否@发送者
        :param at_all: 是否@所有人
        :return: 卡片的实例ID
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error(
                "CardResponder.send_card failed, cannot get dingtalk access token"
            )
            return ""

        card_instance_id = self.gen_card_id(self.incoming_message)
        body = {
            "cardTemplateId": card_template_id,
            "outTrackId": card_instance_id,
            "cardData": {"cardParamMap": card_data},
            "callbackType": callback_type,
            "imGroupOpenSpaceModel": {"supportForward": support_forward},
            "imRobotOpenSpaceModel": {"supportForward": support_forward},
        }

        if callback_type == "HTTP":
            body["callbackType"] = "HTTP"
            body["callbackRouteKey"] = callback_route_key

        # 创建卡片实例。https://open.dingtalk.com/document/orgapp/interface-for-creating-a-card-instance
        url = DINGTALK_OPENAPI_ENDPOINT + "/v1.0/card/instances"
        try:
            response_text = ""
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=self.get_request_header(access_token), json=body
                ) as response:
                    response_text = await response.text()
                    
                    response.raise_for_status()
        except aiohttp.ClientResponseError as e:
            self.logger.error(
                f"CardReplier.async_create_and_send_card failed, create card instance failed, HTTP Error: {e.status}, URL: {url}, response.text: {response_text}"
            )
        except Exception as e:
            self.logger.error(
                f"CardReplier.async_create_and_send_card create card instance unexpected error occurred: {e}"
            )

        body = {"outTrackId": card_instance_id, "userIdType": 1}

        # 2：群聊，1：单聊
        if self.incoming_message.conversation_type == "2":
            body["openSpaceId"] = "dtv1.card//{spaceType}.{spaceId}".format(
                spaceType="IM_GROUP", spaceId=self.incoming_message.conversation_id
            )
            body["imGroupOpenDeliverModel"] = {
                "robotCode": self.dingtalk_client.credential.client_id,
            }

            if at_all:
                body["imGroupOpenDeliverModel"]["atUserIds"] = {
                    "@ALL": "@ALL",
                }
            elif at_sender:
                body["imGroupOpenDeliverModel"]["atUserIds"] = {
                    self.incoming_message.sender_staff_id: self.incoming_message.sender_nick,
                }

            if recipients is not None:
                body["imGroupOpenDeliverModel"]["recipients"] = recipients

            # 增加托管extension
            if self.incoming_message.hosting_context is not None:
                body["imGroupOpenDeliverModel"]["extension"] = {
                    "hostingRepliedContext": json.dumps(
                        {"userId": self.incoming_message.hosting_context.user_id}
                    )
                }
        elif self.incoming_message.conversation_type == "1":
            body["openSpaceId"] = "dtv1.card//{spaceType}.{spaceId}".format(
                spaceType="IM_ROBOT", spaceId=self.incoming_message.sender_staff_id
            )
            body["imRobotOpenDeliverModel"] = {"spaceType": "IM_ROBOT"}

            # 增加托管extension
            if self.incoming_message.hosting_context is not None:
                body["imRobotOpenDeliverModel"]["extension"] = {
                    "hostingRepliedContext": json.dumps(
                        {"userId": self.incoming_message.hosting_context.user_id}
                    )
                }

        # 投放卡片。https://open.dingtalk.com/document/orgapp/delivery-card-interface
        url = DINGTALK_OPENAPI_ENDPOINT + "/v1.0/card/instances/deliver"
        try:
            response_text = ""
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=self.get_request_header(access_token), json=body
                ) as response:
                    response_text = await response.text()
                    
                    response.raise_for_status()

            return card_instance_id
        except aiohttp.ClientResponseError as e:
            self.logger.error(
                f"CardReplier.async_create_and_send_card failed, send card failed, HTTP Error: {e.status}, URL: {url}, response.text: {response_text}"
            )
        except Exception as e:
            self.logger.error(
                f"CardReplier.async_create_and_send_card send card unexpected error occurred: {e}"
            )

    def create_and_deliver_card(
        self,
        card_template_id: str,
        card_data: dict,
        callback_type: str = "STREAM",
        callback_route_key: str = "",
        at_sender: bool = False,
        at_all: bool = False,
        recipients: list = None,
        support_forward: bool = True,
        **kwargs,
    ) -> str:
        """
        创建并发送卡片一步到位，支持传入其他参数以达到投放吊顶场域卡片的效果等等。
        https://open.dingtalk.com/document/orgapp/create-and-deliver-cards
        :param support_forward: 卡片是否支持转发
        :param callback_route_key: HTTP 回调时的 route key
        :param callback_type: 卡片回调模式
        :param recipients: 接收者
        :param card_template_id: 卡片模板 ID
        :param card_data: 卡片数据
        :param at_sender: 是否@发送者
        :param at_all: 是否@所有人
        :param kwargs: 其他参数，如覆盖 openSpaceId，配置动态数据源 openDynamicDataConfig，配置吊顶场域 topOpenSpaceModel、topOpenDeliverModel 等等
        :return: 卡片的实例ID
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error(
                "CardResponder.send_card failed, cannot get dingtalk access token"
            )
            return ""

        card_instance_id = self.gen_card_id(self.incoming_message)
        body = {
            "cardTemplateId": card_template_id,
            "outTrackId": card_instance_id,
            "cardData": {"cardParamMap": card_data},
            "callbackType": callback_type,
            "imGroupOpenSpaceModel": {"supportForward": support_forward},
            "imRobotOpenSpaceModel": {"supportForward": support_forward},
        }

        if callback_type == "HTTP":
            body["callbackType"] = "HTTP"
            body["callbackRouteKey"] = callback_route_key

            # 2：群聊，1：单聊
        if self.incoming_message.conversation_type == "2":
            body["openSpaceId"] = "dtv1.card//{spaceType}.{spaceId}".format(
                spaceType="IM_GROUP", spaceId=self.incoming_message.conversation_id
            )
            body["imGroupOpenDeliverModel"] = {
                "robotCode": self.dingtalk_client.credential.client_id,
            }

            if at_all:
                body["imGroupOpenDeliverModel"]["atUserIds"] = {
                    "@ALL": "@ALL",
                }
            elif at_sender:
                body["imGroupOpenDeliverModel"]["atUserIds"] = {
                    self.incoming_message.sender_staff_id: self.incoming_message.sender_nick,
                }

            if recipients is not None:
                body["imGroupOpenDeliverModel"]["recipients"] = recipients

            # 增加托管extension
            if self.incoming_message.hosting_context is not None:
                body["imGroupOpenDeliverModel"]["extension"] = {
                    "hostingRepliedContext": json.dumps(
                        {"userId": self.incoming_message.hosting_context.user_id}
                    )
                }
        elif self.incoming_message.conversation_type == "1":
            body["openSpaceId"] = "dtv1.card//{spaceType}.{spaceId}".format(
                spaceType="IM_ROBOT", spaceId=self.incoming_message.sender_staff_id
            )
            body["imRobotOpenDeliverModel"] = {"spaceType": "IM_ROBOT"}

            # 增加托管extension
            if self.incoming_message.hosting_context is not None:
                body["imRobotOpenDeliverModel"]["extension"] = {
                    "hostingRepliedContext": json.dumps(
                        {"userId": self.incoming_message.hosting_context.user_id}
                    )
                }

        url = DINGTALK_OPENAPI_ENDPOINT + "/v1.0/card/instances/createAndDeliver"
        try:
            response_text = ""
            body = {**body, **kwargs}
            response = requests.post(
                url, headers=self.get_request_header(access_token), json=body
            )
            response_text = response.text
            
            response.raise_for_status()
        except Exception as e:
            self.logger.error(
                f"CardReplier.create_and_deliver_card failed, error={e}, response.text={response_text}"
            )

        return card_instance_id

    async def async_create_and_deliver_card(
        self,
        card_template_id: str,
        card_data: dict,
        callback_type: str = "STREAM",
        callback_route_key: str = "",
        at_sender: bool = False,
        at_all: bool = False,
        recipients: list = None,
        support_forward: bool = True,
        **kwargs,
    ) -> str:
        """
        创建并发送卡片一步到位，支持传入其他参数以达到投放吊顶场域卡片的效果等等。
        https://open.dingtalk.com/document/orgapp/create-and-deliver-cards
        :param support_forward: 卡片是否支持转发
        :param callback_route_key: HTTP 回调时的 route key
        :param callback_type: 卡片回调模式
        :param recipients: 接收者
        :param card_template_id: 卡片模板 ID
        :param card_data: 卡片数据
        :param at_sender: 是否@发送者
        :param at_all: 是否@所有人
        :param kwargs: 其他参数，如覆盖 openSpaceId，配置动态数据源 openDynamicDataConfig，配置吊顶场域 topOpenSpaceModel、topOpenDeliverModel 等等
        :return: 卡片的实例ID
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error(
                "CardResponder.send_card failed, cannot get dingtalk access token"
            )
            return ""

        card_instance_id = self.gen_card_id(self.incoming_message)
        body = {
            "cardTemplateId": card_template_id,
            "outTrackId": card_instance_id,
            "cardData": {"cardParamMap": card_data},
            "callbackType": callback_type,
            "imGroupOpenSpaceModel": {"supportForward": support_forward},
            "imRobotOpenSpaceModel": {"supportForward": support_forward},
        }

        if callback_type == "HTTP":
            body["callbackType"] = "HTTP"
            body["callbackRouteKey"] = callback_route_key

            # 2：群聊，1：单聊
        if self.incoming_message.conversation_type == "2":
            body["openSpaceId"] = "dtv1.card//{spaceType}.{spaceId}".format(
                spaceType="IM_GROUP", spaceId=self.incoming_message.conversation_id
            )
            body["imGroupOpenDeliverModel"] = {
                "robotCode": self.dingtalk_client.credential.client_id,
            }

            if at_all:
                body["imGroupOpenDeliverModel"]["atUserIds"] = {
                    "@ALL": "@ALL",
                }
            elif at_sender:
                body["imGroupOpenDeliverModel"]["atUserIds"] = {
                    self.incoming_message.sender_staff_id: self.incoming_message.sender_nick,
                }

            if recipients is not None:
                body["imGroupOpenDeliverModel"]["recipients"] = recipients

            # 增加托管extension
            if self.incoming_message.hosting_context is not None:
                body["imGroupOpenDeliverModel"]["extension"] = {
                    "hostingRepliedContext": json.dumps(
                        {"userId": self.incoming_message.hosting_context.user_id}
                    )
                }
        elif self.incoming_message.conversation_type == "1":
            body["openSpaceId"] = "dtv1.card//{spaceType}.{spaceId}".format(
                spaceType="IM_ROBOT", spaceId=self.incoming_message.sender_staff_id
            )
            body["imRobotOpenDeliverModel"] = {"spaceType": "IM_ROBOT"}

            # 增加托管extension
            if self.incoming_message.hosting_context is not None:
                body["imRobotOpenDeliverModel"]["extension"] = {
                    "hostingRepliedContext": json.dumps(
                        {"userId": self.incoming_message.hosting_context.user_id}
                    )
                }

        url = DINGTALK_OPENAPI_ENDPOINT + "/v1.0/card/instances/createAndDeliver"

        body = {**body, **kwargs}
        async with aiohttp.ClientSession() as session:
            try:
                response_text = ""
                async with session.post(
                    url, headers=self.get_request_header(access_token), json=body
                ) as response:
                    response_text = await response.text()
                    
                    response.raise_for_status()
            except aiohttp.ClientResponseError as e:
                self.logger.error(
                    f"CardReplier.async_create_and_deliver_card failed, HTTP Error: {e.status}, URL: {url}, response.text: {response_text}"
                )
            except Exception as e:
                self.logger.error(
                    f"CardReplier.async_create_and_deliver_card unexpected error occurred: {e}"
                )

        return card_instance_id

    def put_card_data(self, card_instance_id: str, card_data: dict, **kwargs):
        """
        更新卡片内容
        https://open.dingtalk.com/document/orgapp/interactive-card-update-interface
        :param card_instance_id:
        :param card_data:
        :param kwargs: 其他参数，如 privateData、cardUpdateOptions、userIdType
        :return:
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error(
                "CardReplier.put_card_data failed, cannot get dingtalk access token"
            )
            return

        body = {
            "outTrackId": card_instance_id,
            "cardData": {"cardParamMap": card_data},
            **kwargs,
        }

        url = DINGTALK_OPENAPI_ENDPOINT + "/v1.0/card/instances"
        try:
            response_text = ""
            response = requests.put(
                url, headers=self.get_request_header(access_token), json=body
            )
            response_text = response.text

            response.raise_for_status()
        except Exception as e:
            self.logger.error(
                f"CardReplier.put_card_data failed, update card failed, error={e}, response.text={response_text}"
            )
            return

    async def async_put_card_data(
        self, card_instance_id: str, card_data: dict, **kwargs
    ):
        """
        更新卡片内容
        https://open.dingtalk.com/document/orgapp/interactive-card-update-interface
        :param card_instance_id:
        :param card_data:
        :param kwargs: 其他参数，如 privateData、cardUpdateOptions、userIdType
        :return:
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error(
                "CardReplier.put_card_data failed, cannot get dingtalk access token"
            )
            return

        body = {
            "outTrackId": card_instance_id,
            "cardData": {"cardParamMap": card_data},
            **kwargs,
        }

        url = DINGTALK_OPENAPI_ENDPOINT + "/v1.0/card/instances"
        try:
            response_text = ""
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url, headers=self.get_request_header(access_token), json=body
                ) as response:
                    response_text = await response.text()
                    
                    response.raise_for_status()
        except aiohttp.ClientResponseError as e:
            self.logger.error(
                f"CardReplier.async_put_card_data failed, HTTP Error: {e.status}, URL: {url}, response.text: {response_text}"
            )
        except Exception as e:
            self.logger.error(
                f"CardReplier.async_put_card_data unexpected error occurred: {e}"
            )


@unique
class AICardStatus(str, Enum):
    PROCESSING: str = 1  # 处理中
    INPUTING: str = 2  # 输入中
    EXECUTING: str = 4  # 执行中
    FINISHED: str = 3  # 执行完成
    FAILED: str = 5  # 执行失败


class AICardReplier(CardReplier):

    def __init__(self, dingtalk_client, incoming_message):
        super(AICardReplier, self).__init__(dingtalk_client, incoming_message)

    def start(
        self,
        card_template_id: str,
        card_data: dict,
        recipients: list = None,
        support_forward: bool = True,
    ) -> str:
        """
        AI卡片的创建接口
        :param support_forward:
        :param recipients:
        :param card_template_id:
        :param card_data:
        :return:
        """
        card_data_with_status = copy.deepcopy(card_data)
        card_data_with_status["flowStatus"] = AICardStatus.PROCESSING
        return self.create_and_send_card(
            card_template_id,
            card_data_with_status,
            at_sender=False,
            at_all=False,
            recipients=recipients,
            support_forward=support_forward,
        )

    async def async_start(
        self,
        card_template_id: str,
        card_data: dict,
        recipients: list = None,
        support_forward: bool = True,
    ) -> str:
        """
        AI卡片的创建接口
        :param support_forward:
        :param recipients:
        :param card_template_id:
        :param card_data:
        :return:
        """
        card_data_with_status = copy.deepcopy(card_data)
        card_data_with_status["flowStatus"] = AICardStatus.PROCESSING
        return await self.async_create_and_send_card(
            card_template_id,
            card_data_with_status,
            at_sender=False,
            at_all=False,
            recipients=recipients,
            support_forward=support_forward,
        )

    def finish(self, card_instance_id: str, card_data: dict):
        """
        AI卡片执行完成的接口，整体更新
        :param card_instance_id:
        :param card_data:
        :return:
        """
        card_data_with_status = copy.deepcopy(card_data)
        card_data_with_status["flowStatus"] = AICardStatus.FINISHED
        self.put_card_data(card_instance_id, card_data_with_status)

    async def async_finish(self, card_instance_id: str, card_data: dict):
        """
        AI卡片执行完成的接口，整体更新
        :param card_instance_id:
        :param card_data:
        :return:
        """
        card_data_with_status = copy.deepcopy(card_data)
        card_data_with_status["flowStatus"] = AICardStatus.FINISHED
        await self.async_put_card_data(card_instance_id, card_data_with_status)

    def fail(self, card_instance_id: str, card_data: dict):
        """
        AI卡片变成失败状态的接口，整体更新，非streaming
        :param card_instance_id:
        :param card_data:
        :return:
        """
        card_data_with_status = copy.deepcopy(card_data)
        card_data_with_status["flowStatus"] = AICardStatus.FAILED
        self.put_card_data(card_instance_id, card_data_with_status)

    async def async_fail(self, card_instance_id: str, card_data: dict):
        """
        AI卡片变成失败状态的接口，整体更新，非streaming
        :param card_instance_id:
        :param card_data:
        :return:
        """
        card_data_with_status = copy.deepcopy(card_data)
        card_data_with_status["flowStatus"] = AICardStatus.FAILED
        await self.async_put_card_data(card_instance_id, card_data_with_status)

    def streaming(
        self,
        card_instance_id: str,
        content_key: str,
        content_value: str,
        append: bool,
        finished: bool,
        failed: bool,
    ):
        """
        AI卡片的流式输出
        :param card_instance_id:
        :param content_key:
        :param content_value:
        :param append:
        :param finished:
        :param failed:
        :return:
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error(
                "AICardReplier.streaming failed, cannot get dingtalk access token"
            )
            return None

        body = {
            "outTrackId": card_instance_id,
            "guid": str(uuid.uuid1()),
            "key": content_key,
            "content": content_value,
            "isFull": not append,
            "isFinalize": finished,
            "isError": failed,
        }

        url = DINGTALK_OPENAPI_ENDPOINT + "/v1.0/card/streaming"
        try:
            response_text = ''
            response = requests.put(
                url, headers=self.get_request_header(access_token), json=body
            )
            response_text = response.text

            response.raise_for_status()
        except Exception as e:
            self.logger.error(
                f"AICardReplier.streaming failed, error={e}, response.text={response_text}"
            )
            return

    async def async_streaming(
        self,
        card_instance_id: str,
        content_key: str,
        content_value: str,
        append: bool,
        finished: bool,
        failed: bool,
    ):
        """
        AI卡片的流式输出
        :param card_instance_id:
        :param content_key:
        :param content_value:
        :param append:
        :param finished:
        :param failed:
        :return:
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error(
                "AICardReplier.streaming failed, cannot get dingtalk access token"
            )
            return None

        body = {
            "outTrackId": card_instance_id,
            "guid": str(uuid.uuid1()),
            "key": content_key,
            "content": content_value,
            "isFull": not append,
            "isFinalize": finished,
            "isError": failed,
        }

        url = DINGTALK_OPENAPI_ENDPOINT + "/v1.0/card/streaming"
        try:
            response_text = ''
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url, headers=self.get_request_header(access_token), json=body
                ) as response:
                    response_text = await response.text()
                    
                    response.raise_for_status()
        except aiohttp.ClientResponseError as e:
            self.logger.error(
                f"AICardReplier.async_streaming failed, HTTP Error: {e.status}, URL: {url}, response.text={response_text}"
            )
        except Exception as e:
            self.logger.error(
                f"CardReplier.async_streaming unexpected error occurred: {e}"
            )
