# -*- coding:utf-8 -*-

import json
import requests
import platform
import hashlib
from .stream import CallbackHandler, CallbackMessage
from .frames import AckMessage, Headers
from .interactive_card import generate_multi_text_line_card_data
from .utils import DINGTALK_OPENAPI_ENDPOINT
from concurrent.futures import ThreadPoolExecutor
import uuid
from .card_instance import MarkdownCardInstance, AIMarkdownCardInstance, CarouselCardInstance, \
    MarkdownButtonCardInstance, RPAPluginCardInstance
import traceback


class AtUser(object):
    def __init__(self):
        self.dingtalk_id = None
        self.staff_id = None
        self.extensions = {}

    @classmethod
    def from_dict(cls, d):
        user = AtUser()
        data = ''
        for name, value in d.items():
            if name == 'dingtalkId':
                user.dingtalk_id = value
            elif name == 'staffId':
                user.staff_id = value
            else:
                user.extensions[name] = value
        return user

    def to_dict(self):
        result = self.extensions.copy()
        if self.dingtalk_id is not None:
            result['dingtalkId'] = self.dingtalk_id
        if self.staff_id is not None:
            result['staffId'] = self.staff_id
        return result


class TextContent(object):
    content: str

    def __init__(self):
        self.content = None
        self.extensions = {}

    def __str__(self):
        return 'TextContent(content=%s)' % self.content

    @classmethod
    def from_dict(cls, d):
        content = TextContent()
        data = ''
        for name, value in d.items():
            if name == 'content':
                content.content = value
            else:
                content.extensions[name] = value
        return content

    def to_dict(self):
        result = self.extensions.copy()
        if self.content is not None:
            result['content'] = self.content
        return result


class ImageContent(object):

    def __init__(self):
        self.download_code = None

    @classmethod
    def from_dict(cls, d):
        content = ImageContent()
        for name, value in d.items():
            if name == 'downloadCode':
                content.download_code = value
        return content

    def to_dict(self):
        result = {}
        if self.download_code is not None:
            result['downloadCode'] = self.download_code
        return result


class RichTextContent(object):

    def __init__(self):
        self.rich_text_list = None

    @classmethod
    def from_dict(cls, d):
        content = RichTextContent()
        content.rich_text_list = []
        for name, value in d.items():
            if name == 'richText':
                content.rich_text_list = value
        return content

    def to_dict(self):
        result = {}
        if self.rich_text_list is not None:
            result['richText'] = self.rich_text_list
        return result


class HostingContext(object):
    """
    托管人的上下文
    """

    def __init__(self):
        self.user_id = ""
        self.nick = ""

    def to_dict(self):
        result = {
            "userId": self.user_id,
            "nick": self.nick,
        }
        return result


class ConversationMessage(object):
    """
    历史消息状态
    """

    def __init__(self):
        self.read_status = ""
        self.sender_user_id = ""
        self.send_time = 0

    def read_by_me(self) -> bool:
        """
        消息是否被我已读
        :return:
        """
        return self.read_status == "2"

    def to_dict(self):
        result = {
            "readStatus": self.read_status,
            "senderUserId": self.sender_user_id,
            "sendTime": self.send_time
        }
        return result


class ChatbotMessage(object):
    TOPIC = '/v1.0/im/bot/messages/get'
    DELEGATE_TOPIC = '/v1.0/im/bot/messages/delegate'
    text: TextContent

    def __init__(self):
        self.is_in_at_list = None
        self.session_webhook = None
        self.sender_nick = None
        self.robot_code = None
        self.session_webhook_expired_time = None
        self.message_id = None
        self.sender_id = None
        self.chatbot_user_id = None
        self.conversation_id = None
        self.is_admin = None
        self.create_at = None
        self.text = None
        self.conversation_type = None
        self.at_users = []
        self.chatbot_corp_id = None
        self.sender_corp_id = None
        self.conversation_title = None
        self.message_type = None
        self.image_content = None
        self.rich_text_content = None
        self.sender_staff_id = None
        self.hosting_context: HostingContext = None
        self.conversation_msg_context = None

        self.extensions = {}

    @classmethod
    def from_dict(cls, d):
        msg = ChatbotMessage()
        data = ''
        for name, value in d.items():
            if name == 'isInAtList':
                msg.is_in_at_list = value
            elif name == 'sessionWebhook':
                msg.session_webhook = value
            elif name == 'senderNick':
                msg.sender_nick = value
            elif name == 'robotCode':
                msg.robot_code = value
            elif name == 'sessionWebhookExpiredTime':
                msg.session_webhook_expired_time = int(value)
            elif name == 'msgId':
                msg.message_id = value
            elif name == 'senderId':
                msg.sender_id = value
            elif name == 'chatbotUserId':
                msg.chatbot_user_id = value
            elif name == 'conversationId':
                msg.conversation_id = value
            elif name == 'isAdmin':
                msg.is_admin = value
            elif name == 'createAt':
                msg.create_at = value
            elif name == 'conversationType':
                msg.conversation_type = value
            elif name == 'atUsers':
                msg.at_users = [AtUser.from_dict(i) for i in value]
            elif name == 'chatbotCorpId':
                msg.chatbot_corp_id = value
            elif name == 'senderCorpId':
                msg.sender_corp_id = value
            elif name == 'conversationTitle':
                msg.conversation_title = value
            elif name == 'msgtype':
                msg.message_type = value
                if value == 'text':
                    msg.text = TextContent.from_dict(d['text'])
                elif value == 'picture':
                    msg.image_content = ImageContent.from_dict(d['content'])
                elif value == 'richText':
                    msg.rich_text_content = RichTextContent.from_dict(d['content'])
            elif name == 'senderStaffId':
                msg.sender_staff_id = value
            elif name == 'hostingContext':
                msg.hosting_context = HostingContext()
                msg.hosting_context.user_id = value["userId"]
                msg.hosting_context.nick = value["nick"]
            elif name == 'conversationMsgContext':
                msg.conversation_msg_context = []
                for v in value:
                    conversation_msg = ConversationMessage()
                    conversation_msg.read_status = v["readStatus"]
                    conversation_msg.send_time = v["sendTime"]
                    conversation_msg.sender_user_id = v["senderUserId"]

                    msg.conversation_msg_context.append(conversation_msg)
            else:
                msg.extensions[name] = value
        return msg

    def to_dict(self):
        result = self.extensions.copy()
        if self.is_in_at_list is not None:
            result['isInAtList'] = self.is_in_at_list
        if self.session_webhook is not None:
            result['sessionWebhook'] = self.session_webhook
        if self.sender_nick is not None:
            result['senderNick'] = self.sender_nick
        if self.robot_code is not None:
            result['robotCode'] = self.robot_code
        if self.session_webhook_expired_time is not None:
            result['sessionWebhookExpiredTime'] = self.session_webhook_expired_time
        if self.message_id is not None:
            result['msgId'] = self.message_id
        if self.sender_id is not None:
            result['senderId'] = self.sender_id
        if self.chatbot_user_id is not None:
            result['chatbotUserId'] = self.chatbot_user_id
        if self.conversation_id is not None:
            result['conversationId'] = self.conversation_id
        if self.is_admin is not None:
            result['isAdmin'] = self.is_admin
        if self.create_at is not None:
            result['createAt'] = self.create_at
        if self.text is not None:
            result['text'] = self.text.to_dict()
        if self.image_content is not None:
            result['content'] = self.image_content.to_dict()
        if self.rich_text_content is not None:
            result['content'] = self.rich_text_content.to_dict()
        if self.conversation_type is not None:
            result['conversationType'] = self.conversation_type
        if self.at_users is not None:
            result['atUsers'] = [i.to_dict() for i in self.at_users]
        if self.chatbot_corp_id is not None:
            result['chatbotCorpId'] = self.chatbot_corp_id
        if self.sender_corp_id is not None:
            result['senderCorpId'] = self.sender_corp_id
        if self.conversation_title is not None:
            result['conversationTitle'] = self.conversation_title
        if self.message_type is not None:
            result['msgtype'] = self.message_type
        if self.sender_staff_id is not None:
            result['senderStaffId'] = self.sender_staff_id
        if self.hosting_context is not None:
            result['hostingContext'] = self.hosting_context.to_dict()
        if self.conversation_msg_context is not None:
            result['conversationMsgContext'] = [v.to_dict() for v in self.conversation_msg_context]
        return result

    def get_text_list(self):
        if self.message_type == 'text':
            return [self.text.content]
        elif self.message_type == 'richText':
            text = []
            for item in self.rich_text_content.rich_text_list:
                if 'text' in item:
                    text.append(item["text"])

            return text

    def get_image_list(self):
        if self.message_type == 'picture':
            return [self.image_content.download_code]
        elif self.message_type == 'richText':
            images = []
            for item in self.rich_text_content.rich_text_list:
                if 'downloadCode' in item:
                    images.append(item['downloadCode'])

            return images

    def __str__(self):
        return 'ChatbotMessage(message_type=%s, text=%s, sender_nick=%s, conversation_title=%s)' % (
            self.message_type,
            self.text,
            self.sender_nick,
            self.conversation_title,
        )


def reply_specified_single_chat(user_id: str, user_nickname: str = "") -> ChatbotMessage:
    d = {
        "senderId": user_id,
        "senderStaffId": user_id,
        "sender": user_nickname,
        "conversationType": '1',
        "messageId": str(uuid.uuid1()),
    }
    return ChatbotMessage.from_dict(d)


def reply_specified_group_chat(open_conversation_id: str) -> ChatbotMessage:
    d = {
        "conversationId": open_conversation_id,
        "conversationType": '2',
        "messageId": str(uuid.uuid1()),
    }
    return ChatbotMessage.from_dict(d)


class ChatbotHandler(CallbackHandler):

    def __init__(self):
        super(ChatbotHandler, self).__init__()

    def reply_markdown_card(self, markdown: str, incoming_message: ChatbotMessage, title: str = "", logo: str = "",
                            at_sender: bool = False, at_all: bool = False) -> MarkdownCardInstance:
        """
        回复一个markdown卡片
        :param markdown:
        :param incoming_message:
        :param title:
        :param logo:
        :param at_sender:
        :param at_all:
        :return:
        """
        markdown_card_instance = MarkdownCardInstance(self.dingtalk_client, incoming_message)
        markdown_card_instance.set_title_and_logo(title, logo)

        markdown_card_instance.reply(markdown, at_sender=at_sender, at_all=at_all)

        return markdown_card_instance

    def reply_rpa_plugin_card(self, incoming_message: ChatbotMessage,
                              plugin_id: str = "",
                              plugin_version: str = "",
                              plugin_name: str = "",
                              ability_name: str = "",
                              plugin_args: dict = {},
                              goal: str = "",
                              corp_id: str = "",
                              recipients: list = None) -> RPAPluginCardInstance:
        """
        回复一个markdown卡片
        :param ability_name:
        :param incoming_message:
        :param recipients:
        :param corp_id:
        :param goal:
        :param plugin_args:
        :param plugin_name:
        :param plugin_version:
        :param plugin_id:
        :return:
        """

        rpa_plugin_card_instance = RPAPluginCardInstance(self.dingtalk_client, incoming_message)
        rpa_plugin_card_instance.set_goal(goal)
        rpa_plugin_card_instance.set_corp_id(corp_id)

        rpa_plugin_card_instance.reply(plugin_id, plugin_version, plugin_name, ability_name, plugin_args,
                                       recipients=recipients)

        return rpa_plugin_card_instance

    def reply_markdown_button(self, incoming_message: ChatbotMessage, markdown: str, button_list: list, tips: str = "",
                              title: str = "", logo: str = "") -> MarkdownButtonCardInstance:
        """
        回复一个带button的卡片
        :param tips:
        :param incoming_message:
        :param markdown:
        :param button_list:
        :param title:
        :param logo:
        :return:
        """
        markdown_button_instance = MarkdownButtonCardInstance(self.dingtalk_client, incoming_message)
        markdown_button_instance.set_title_and_logo(title, logo)

        markdown_button_instance.reply(markdown, button_list, tips=tips)

        return markdown_button_instance

    def reply_ai_markdown_button(self,
                                 incoming_message: ChatbotMessage,
                                 markdown: str,
                                 button_list: list,
                                 tips: str = "",
                                 title: str = "",
                                 logo: str = "",
                                 recipients: list = None,
                                 support_forward: bool = True) -> AIMarkdownCardInstance:
        """
        回复一个带button的ai卡片
        :param support_forward:
        :param recipients:
        :param tips:
        :param incoming_message:
        :param markdown:
        :param button_list:
        :param title:
        :param logo:
        :return:
        """
        markdown_button_instance = AIMarkdownCardInstance(self.dingtalk_client, incoming_message)
        markdown_button_instance.set_title_and_logo(title, logo)

        markdown_button_instance.ai_start(recipients=recipients, support_forward=support_forward)
        markdown_button_instance.ai_streaming(markdown=markdown, append=True)
        markdown_button_instance.ai_finish(markdown=markdown, button_list=button_list, tips=tips)

        return markdown_button_instance

    def reply_carousel_card(self, incoming_message: ChatbotMessage, markdown: str, image_slider, button_text,
                            title: str = "",
                            logo: str = "") -> CarouselCardInstance:
        """
        回复一个轮播图卡片
        :param markdown:
        :param incoming_message:
        :param title:
        :param logo:
        :param image_slider:
        :param button_text:
        :return:
        """
        carousel_card_instance = CarouselCardInstance(self.dingtalk_client, incoming_message)
        carousel_card_instance.set_title_and_logo(title, logo)

        carousel_card_instance.reply(markdown, image_slider, button_text)

        return carousel_card_instance

    def ai_markdown_card_start(self, incoming_message: ChatbotMessage, title: str = "",
                               logo: str = "", recipients: list = None) -> AIMarkdownCardInstance:
        """
        发起一个AI卡片
        :param recipients:
        :param incoming_message:
        :param title:
        :param logo:
        :return:
        """
        ai_markdown_card_instance = AIMarkdownCardInstance(self.dingtalk_client, incoming_message)
        ai_markdown_card_instance.set_title_and_logo(title, logo)

        ai_markdown_card_instance.ai_start(recipients=recipients)
        return ai_markdown_card_instance

    def extract_text_from_incoming_message(self, incoming_message: ChatbotMessage) -> list:
        """
        获取文本列表
        :param incoming_message:
        :return: text list。如果是纯文本消息，结果列表中只有一个元素；如果是富文本消息，结果是长列表，按富文本消息的逻辑分割，大致是按换行符分割的。
        """
        return incoming_message.get_text_list()

    def extract_image_from_incoming_message(self, incoming_message: ChatbotMessage) -> list:
        """
        获取用户发送的图片，重新上传，获取新的mediaId列表
        :param incoming_message:
        :return: mediaid list
        """
        image_list = incoming_message.get_image_list()
        if image_list is None or len(image_list) == 0:
            return None

        mediaids = []
        for download_code in image_list:
            download_url = self.get_image_download_url(download_code)

            image_content = requests.get(download_url)
            mediaid = self.dingtalk_client.upload_to_dingtalk(image_content.content, filetype='image',
                                                              filename='image.png',
                                                              mimetype='image/png')

            mediaids.append(mediaid)

        return mediaids

    def get_image_download_url(self, download_code: str) -> str:
        """
        根据downloadCode获取下载链接 https://open.dingtalk.com/document/isvapp/download-the-file-content-of-the-robot-receiving-message
        :param download_code:
        :return:
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error('send_off_duty_prompt failed, cannot get dingtalk access token')
            return None

        request_headers = {
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'x-acs-dingtalk-access-token': access_token,
            'User-Agent': ('DingTalkStream/1.0 SDK/0.1.0 Python/%s '
                           '(+https://github.com/open-dingtalk/dingtalk-stream-sdk-python)'
                           ) % platform.python_version(),
        }

        values = {
            'robotCode': self.dingtalk_client.credential.client_id,
            'downloadCode': download_code,
        }

        url = DINGTALK_OPENAPI_ENDPOINT + '/v1.0/robot/messageFiles/download'

        try:
            response_text = ''
            response = requests.post(url,
                                     headers=request_headers,
                                     data=json.dumps(values))
            response_text = response.text

            response.raise_for_status()
        except Exception as e:
            self.logger.error(f'get_image_download_url, error={e}, response.text={response_text}')
            return ""
        return response.json()["downloadUrl"]

    def set_off_duty_prompt(self, text: str, title: str = "", logo: str = ""):
        """
        设置离线提示词，需要使用OpenAPI，当前仅支持自建应用。
        :param text: 离线提示词，支持markdown
        :param title: 机器人名称，默认："钉钉Stream机器人"
        :param logo: 机器人logo，默认："@lALPDfJ6V_FPDmvNAfTNAfQ"
        :return:
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error('send_off_duty_prompt failed, cannot get dingtalk access token')
            return None

        if title is None or title == "":
            title = "钉钉Stream机器人"

        if logo is None or logo == "":
            logo = "@lALPDfJ6V_FPDmvNAfTNAfQ"

        prompt_card_data = generate_multi_text_line_card_data(title=title, logo=logo, texts=[text])

        request_headers = {
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'x-acs-dingtalk-access-token': access_token,
            'User-Agent': ('DingTalkStream/1.0 SDK/0.1.0 Python/%s '
                           '(+https://github.com/open-dingtalk/dingtalk-stream-sdk-python)'
                           ) % platform.python_version(),
        }

        values = {
            'robotCode': self.dingtalk_client.credential.client_id,
            'cardData': json.dumps(prompt_card_data),
            'cardTemplateId': "StandardCard",
        }

        url = DINGTALK_OPENAPI_ENDPOINT + '/v1.0/innerApi/robot/stream/away/template/update'

        try:
            response_text = ''
            response = requests.post(url,
                                     headers=request_headers,
                                     data=json.dumps(values))
            response_text = response.text

            response.raise_for_status()
        except Exception as e:
            self.logger.error(f'set_off_duty_prompt, error={e}, response.text={response_text}')
            return response.status_code
        return response.json()

    def reply_text(self,
                   text: str,
                   incoming_message: ChatbotMessage):
        request_headers = {
            'Content-Type': 'application/json',
            'Accept': '*/*',
        }
        values = {
            'msgtype': 'text',
            'text': {
                'content': text,
            },
            'at': {
                'atUserIds': [incoming_message.sender_staff_id],
            }
        }
        try:
            response_text = ''
            response = requests.post(incoming_message.session_webhook,
                                     headers=request_headers,
                                     data=json.dumps(values))
            response_text = response.text
            
            response.raise_for_status()
        except Exception as e:
            self.logger.error(f'reply text failed, error={e}, response.text={response_text}')
            return None
        return response.json()

    def reply_markdown(self,
                       title: str,
                       text: str,
                       incoming_message: ChatbotMessage):
        request_headers = {
            'Content-Type': 'application/json',
            'Accept': '*/*',
        }
        values = {
            'msgtype': 'markdown',
            'markdown': {
                'title': title,
                'text': text,
            },
            'at': {
                'atUserIds': [incoming_message.sender_staff_id],
            }
        }
        try:
            response_text = ''
            response = requests.post(incoming_message.session_webhook,
                                     headers=request_headers,
                                     data=json.dumps(values))
            response_text = response.text        

            response.raise_for_status()
        except Exception as e:
            self.logger.error(f'reply markdown failed, error={e}, response.text={response_text}')
            return None
        return response.json()

    def reply_card(self,
                   card_data: dict,
                   incoming_message: ChatbotMessage,
                   at_sender: bool = False,
                   at_all: bool = False,
                   **kwargs) -> str:
        """
        机器人回复互动卡片。由于 sessionWebhook 不支持发送互动卡片，所以需要使用 OpenAPI，当前仅支持自建应用。
        https://open.dingtalk.com/document/orgapp/robots-send-interactive-cards
        :param card_data: 卡片数据内容，interactive_card.py 中有一些简单的样例，高阶需求请至卡片搭建平台：https://card.dingtalk.com/card-builder
        :param incoming_message: 回调数据源
        :param at_sender: 是否at发送人
        :param at_all: 是否at所有人
        :param kwargs: 其他参数，具体可参考文档。
        :return:
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error(
                'simple_reply_interactive_card_only_for_inner_app failed, cannot get dingtalk access token')
            return None

        request_headers = {
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'x-acs-dingtalk-access-token': access_token,
            'User-Agent': ('DingTalkStream/1.0 SDK/0.1.0 Python/%s '
                           '(+https://github.com/open-dingtalk/dingtalk-stream-sdk-python)'
                           ) % platform.python_version(),
        }

        card_biz_id = self._gen_card_id(incoming_message)
        body = {
            "cardTemplateId": "StandardCard",
            "robotCode": self.dingtalk_client.credential.client_id,
            "cardData": json.dumps(card_data),
            "sendOptions": {
                # "atUserListJson": "String",
                # "atAll": at_all,
                # "receiverListJson": "String",
                # "cardPropertyJson": "String"
            },
            "cardBizId": card_biz_id,
        }

        if incoming_message.conversation_type == '2':
            body["openConversationId"] = incoming_message.conversation_id
        elif incoming_message.conversation_type == '1':
            single_chat_receiver = {
                "userId": incoming_message.sender_staff_id
            }
            body["singleChatReceiver"] = json.dumps(single_chat_receiver)

        if at_all:
            body["sendOptions"]["atAll"] = True
        else:
            body["sendOptions"]["atAll"] = False

        if at_sender:
            user_list_json = [
                {
                    "nickName": incoming_message.sender_nick,
                    "userId": incoming_message.sender_staff_id
                }
            ]
            body["sendOptions"]["atUserListJson"] = json.dumps(user_list_json, ensure_ascii=False)
        body.update(**kwargs)

        url = DINGTALK_OPENAPI_ENDPOINT + '/v1.0/im/v1.0/robot/interactiveCards/send'
        try:
            response_text = ''
            response = requests.post(url,
                                     headers=request_headers,
                                     json=body)
            response_text = response.text

            response.raise_for_status()

            return card_biz_id
        except Exception as e:
            self.logger.error(f'reply card failed, error={e}, response.text={response_text}')
            return ""

    def update_card(self, card_biz_id: str, card_data: dict):
        """
        更新机器人发送互动卡片（普通版）。
        https://open.dingtalk.com/document/orgapp/update-the-robot-to-send-interactive-cards
        :param card_biz_id: 唯一标识一张卡片的外部ID（卡片幂等ID，可用于更新或重复发送同一卡片到多个群会话）。需与 self.reply_card 接口返回的 card_biz_id 保持一致。
        :param card_data: 要更新的卡片数据内容。详情参考卡片搭建平台：https://card.dingtalk.com/card-builder
        :return:
        """
        access_token = self.dingtalk_client.get_access_token()
        if not access_token:
            self.logger.error('update_card failed, cannot get dingtalk access token')
            return None

        request_headers = {
            'Content-Type': 'application/json',
            'Accept': '*/*',
            'x-acs-dingtalk-access-token': access_token,
            'User-Agent': ('DingTalkStream/1.0 SDK/0.1.0 Python/%s '
                           '(+https://github.com/open-dingtalk/dingtalk-stream-sdk-python)'
                           ) % platform.python_version(),
        }

        values = {
            'cardBizId': card_biz_id,
            'cardData': json.dumps(card_data),
        }
        url = DINGTALK_OPENAPI_ENDPOINT + '/v1.0/im/robots/interactiveCards'
        try:
            response_text = ''
            response = requests.put(url,
                                    headers=request_headers,
                                    data=json.dumps(values))
            response_text = response.text
            
            response.raise_for_status()
        except Exception as e:
            self.logger.error(f'update card failed, error={e}, response.text={response_text}')
            return response.status_code
        return response.json()

    @staticmethod
    def _gen_card_id(msg: ChatbotMessage):
        factor = '%s_%s_%s_%s_%s' % (
            msg.sender_id, msg.sender_corp_id, msg.conversation_id, msg.message_id, str(uuid.uuid1()))
        m = hashlib.sha256()
        m.update(factor.encode('utf-8'))
        return m.hexdigest()


class AsyncChatbotHandler(ChatbotHandler):
    """
    多任务执行handler，注意：process函数重载的时候不要用 async
    """

    async_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=8)

    def __init__(self, max_workers: int = 8):
        super(AsyncChatbotHandler, self).__init__()
        self.async_executor = ThreadPoolExecutor(max_workers=max_workers)

    def process(self, message):
        '''
        不要用 async 修饰
        :param message:
        :return:
        '''
        return AckMessage.STATUS_NOT_IMPLEMENT, 'not implement'

    async def raw_process(self, callback_message: CallbackMessage):
        def func():
            try:
                self.process(callback_message)
            except Exception as e:
                self.logger.error(traceback.format_exc())

        self.async_executor.submit(func)

        ack_message = AckMessage()
        ack_message.code = AckMessage.STATUS_OK
        ack_message.headers.message_id = callback_message.headers.message_id
        ack_message.headers.content_type = Headers.CONTENT_TYPE_APPLICATION_JSON
        ack_message.message = "ok"
        ack_message.data = callback_message.data
        return ack_message
