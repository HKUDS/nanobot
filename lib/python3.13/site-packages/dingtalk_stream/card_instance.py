# -*- coding:utf-8 -*-

"""
这里提供了一些常用的卡片模板及其封装类
"""

from .card_replier import CardReplier, AICardReplier, AICardStatus
import json


class MarkdownCardInstance(CardReplier):
    """
    一款超级通用的markdown卡片
    """

    def __init__(self, dingtalk_client, incoming_message):
        super(MarkdownCardInstance, self).__init__(dingtalk_client, incoming_message)
        self.card_template_id = "589420e2-c1e2-46ef-a5ed-b8728e654da9.schema"
        self.card_instance_id = None
        self.title = None
        self.logo = None

    def set_title_and_logo(self, title: str, logo: str):
        self.title = title
        self.logo = logo

    def _get_card_data(self, markdown) -> dict:
        card_data = {
            "markdown": markdown,
        }

        if self.title is not None and self.title != "":
            card_data["title"] = self.title

        if self.logo is not None and self.logo != "":
            card_data["logo"] = self.logo

        return card_data

    def reply(self,
              markdown: str,
              at_sender: bool = False,
              at_all: bool = False,
              recipients: list = None,
              support_forward: bool = True):
        """
        回复markdown内容
        :param recipients:
        :param support_forward:
        :param markdown:
        :param title:
        :param logo:
        :param at_sender:
        :param at_all:
        :return:
        """
        self.card_instance_id = self.create_and_send_card(self.card_template_id, self._get_card_data(markdown),
                                                          at_sender=at_sender, at_all=at_all,
                                                          recipients=recipients,
                                                          support_forward=support_forward)

    def update(self, markdown: str):
        """
        更新markdown内容，如果你reply了多次，这里只会更新最后一张卡片
        :param markdown:
        :return:
        """
        if self.card_instance_id is None or self.card_instance_id == "":
            self.logger.error('MarkdownCardInstance.update failed, you should send card first.')
            return

        self.put_card_data(self.card_instance_id, self._get_card_data(markdown))


class MarkdownButtonCardInstance(CardReplier):
    """
    一款超级通用的markdown卡片
    """

    def __init__(self, dingtalk_client, incoming_message):
        super(MarkdownButtonCardInstance, self).__init__(dingtalk_client, incoming_message)
        self.card_template_id = "1366a1eb-bc54-4859-ac88-517c56a9acb1.schema"
        self.card_instance_id = None
        self.title = None
        self.logo = None
        self.button_list = []

    def set_title_and_logo(self, title: str, logo: str):
        self.title = title
        self.logo = logo

    def _get_card_data(self, markdown, tips) -> dict:
        card_data = {
            "markdown": markdown,
            "tips": tips
        }

        if self.title is not None and self.title != "":
            card_data["title"] = self.title

        if self.logo is not None and self.logo != "":
            card_data["logo"] = self.logo

        if self.button_list is not None:
            sys_full_json_obj = {
                "msgButtons": self.button_list
            }

            card_data["sys_full_json_obj"] = json.dumps(sys_full_json_obj)

        return card_data

    def reply(self,
              markdown: str,
              button_list: list,
              tips: str = "",
              recipients: list = None,
              support_forward: bool = True):
        """
        回复markdown内容
        :param support_forward:
        :param recipients:
        :param tips:
        :param button_list: [{"text":"text", "url":"url", "iosUrl":"iosUrl", "color":"gray"}]
        :param markdown:
        :return:
        """
        self.button_list = button_list
        self.card_instance_id = self.create_and_send_card(self.card_template_id, self._get_card_data(markdown, tips),
                                                          recipients=recipients, support_forward=support_forward)

    def update(self,
               markdown: str,
               button_list: list,
               tips: str = ""):
        """
        更新markdown内容，如果你reply了多次，这里只会更新最后一张卡片
        :param button_list:[{"text":"text", "url":"url", "iosUrl":"iosUrl", "color":"gray"}]
        :param tips:
        :param markdown:
        :return:
        """
        if self.card_instance_id is None or self.card_instance_id == "":
            self.logger.error('MarkdownButtonCardInstance.update failed, you should send card first.')
            return

        self.button_list = button_list
        self.put_card_data(self.card_instance_id, self._get_card_data(markdown, tips))


class AIMarkdownCardInstance(AICardReplier):
    """
    一款超级通用的AI Markdown卡片
    ai_start --> ai_streaming --> ai_streaming --> ai_finish/ai_fail
    """

    def __init__(self, dingtalk_client, incoming_message):
        super(AIMarkdownCardInstance, self).__init__(dingtalk_client, incoming_message)
        self.card_template_id = "382e4302-551d-4880-bf29-a30acfab2e71.schema"
        self.card_instance_id = None
        self.title = None
        self.logo = None
        self.markdown = ""
        self.static_markdown = ""
        self.button_list = None
        self.inputing_status = False
        self.order = [
            "msgTitle",
            "msgContent",
            "staticMsgContent",
            "msgTextList",
            "msgImages",
            "msgSlider",
            "msgButtons",
        ]

    def set_title_and_logo(self, title: str, logo: str):
        self.title = title
        self.logo = logo

    def set_order(self, order: list):
        self.order = order

    def get_card_data(self, flow_status=None):
        card_data = {
            "msgContent": self.markdown,
            "staticMsgContent": self.static_markdown,
        }

        if flow_status is not None:
            card_data["flowStatus"] = flow_status

        if self.title is not None and self.title != "":
            card_data["msgTitle"] = self.title

        if self.logo is not None and self.logo != "":
            card_data["logo"] = self.logo

        sys_full_json_obj = {
            "order": self.order,
        }

        if self.button_list is not None and len(self.button_list) > 0:
            sys_full_json_obj["msgButtons"] = self.button_list

        if self.incoming_message.hosting_context is not None:
            sys_full_json_obj["source"] = {
                "text": "由{nick}的数字助理回答".format(nick=self.incoming_message.hosting_context.nick)
            }

        card_data["sys_full_json_obj"] = json.dumps(sys_full_json_obj)

        return card_data

    def ai_start(self, recipients: list = None, support_forward: bool = True):
        """
        开始执行中
        :return:
        """
        if self.card_instance_id is not None and self.card_instance_id != "":
            return

        self.card_instance_id = self.start(self.card_template_id, {}, recipients=recipients,
                                           support_forward=support_forward)
        self.inputing_status = False

    def ai_streaming(self,
                     markdown: str,
                     append: bool = False):
        """
        打字机模式
        :param append: 两种更新模式，append=true，追加的方式；append=false，全量替换。
        :param markdown:
        :return:
        """
        if self.card_instance_id is None or self.card_instance_id == "":
            self.logger.error('AIMarkdownCardInstance.ai_streaming failed, you should send card first.')
            return

        if not self.inputing_status:
            self.put_card_data(self.card_instance_id, self.get_card_data(AICardStatus.INPUTING))

            self.inputing_status = True

        if append:
            self.markdown = self.markdown + markdown
        else:
            self.markdown = markdown

        self.streaming(self.card_instance_id, "msgContent", self.markdown, append=False, finished=False,
                       failed=False)

    def ai_finish(self,
                  markdown: str = None,
                  button_list: list = None,
                  tips: str = ""):
        """
        完成态
        :param tips:
        :param button_list:
        :param markdown:
        :return:
        """
        if self.card_instance_id is None or self.card_instance_id == "":
            self.logger.error('AIMarkdownCardInstance.ai_finish failed, you should send card first.')
            return

        if markdown is not None:
            self.markdown = markdown

        if button_list is not None:
            self.button_list = button_list

        self.finish(self.card_instance_id, self.get_card_data())

    def update(self,
               static_markdown: str = None,
               button_list: list = None,
               tips: str = ""):
        """
        非流式内容输出
        :param static_markdown:
        :param button_list:
        :param tips:
        :return:
        """
        if self.card_instance_id is None or self.card_instance_id == "":
            self.logger.error('AIMarkdownCardInstance.update failed, you should send card first.')
            return

        if button_list is not None:
            self.button_list = button_list

        if static_markdown is not None:
            self.static_markdown = static_markdown

        self.finish(self.card_instance_id, self.get_card_data())

    def ai_fail(self):
        """
        失败态
        :return:
        """

        if self.card_instance_id is None or self.card_instance_id == "":
            self.logger.error('AIMarkdownCardInstance.ai_fail failed, you should send card first.')
            return

        card_data = {}

        if self.title is not None and self.title != "":
            card_data["msgTitle"] = self.title

        if self.logo is not None and self.logo != "":
            card_data["logo"] = self.logo

        self.fail(self.card_instance_id, card_data)


class CarouselCardInstance(AICardReplier):
    """
    轮播图卡片
    """

    def __init__(self, dingtalk_client, incoming_message):
        super(CarouselCardInstance, self).__init__(dingtalk_client, incoming_message)
        self.card_template_id = "382e4302-551d-4880-bf29-a30acfab2e71.schema"
        self.card_instance_id = None
        self.title = None
        self.logo = None

    def set_title_and_logo(self, title: str, logo: str):
        self.title = title
        self.logo = logo

    def ai_start(self):
        """
        开始执行中
        :return:
        """
        self.card_instance_id = self.start(self.card_template_id, {})

    def reply(self,
              markdown: str,
              image_slider_list: list,
              button_text: str = "submit",
              recipients: list = None,
              support_forward: bool = True):
        """
        回复卡片
        :param support_forward:
        :param recipients:
        :param button_text:
        :param image_slider_list:
        :param markdown:
        :return:
        """

        sys_full_json_obj = {
            "order": [
                "msgTitle",
                "staticMsgContent",
                "msgSlider",
                "msgImages",
                "msgTextList",
                "msgButtons",
            ],
            "msgSlider": [],
            "msgButtons": [
                {
                    "text": button_text,
                    "color": "blue",
                    "id": "image_slider_select_button",
                    "request": True
                }
            ]
        }

        if button_text is not None and button_text != "":
            sys_full_json_obj["msgButtons"][0]["text"] = button_text

        for image_slider in image_slider_list:
            sys_full_json_obj["msgSlider"].append({
                "title": image_slider[0],
                "image": image_slider[1]
            })

        card_data = {
            "staticMsgContent": markdown,
            "sys_full_json_obj": json.dumps(sys_full_json_obj)
        }

        if self.title is not None and self.title != "":
            card_data["msgTitle"] = self.title

        if self.logo is not None and self.logo != "":
            card_data["logo"] = self.logo

        self.card_instance_id = self.create_and_send_card(self.card_template_id,
                                                          {"flowStatus": AICardStatus.PROCESSING},
                                                          callback_type="STREAM", recipients=recipients,
                                                          support_forward=support_forward)

        self.finish(self.card_instance_id, card_data)


class RPAPluginCardInstance(AICardReplier):

    def __init__(self, dingtalk_client, incoming_message):
        super(RPAPluginCardInstance, self).__init__(dingtalk_client, incoming_message)
        self.card_template_id = "7f538f6d-ebb7-4533-a9ac-61a32da094cf.schema"
        self.card_instance_id = None
        self.goal = ""
        self.corp_id = ""

    def set_goal(self, goal: str):
        self.goal = goal

    def set_corp_id(self, corp_id: str):
        self.corp_id = corp_id

    def reply(self,
              plugin_id: str,
              plugin_version: str,
              plugin_name: str,
              ability_name: str,
              plugin_args: dict,
              recipients: list = None,
              support_forward: bool = True):
        """
        回复markdown内容
        :param support_forward:
        :param ability_name:
        :param recipients:
        :param plugin_version:
        :param plugin_args:
        :param plugin_name:
        :param plugin_id:
        :return:
        """

        plan = {
            "corpId": self.corp_id,
            "goal": self.goal,
            "plan": "(function(){dd.callPlugin({'pluginName':'%s','abilityName':'%s','args':%s });})()" % (
                plugin_name, ability_name, json.dumps(plugin_args)),
            "planType": "jsCode",
            "pluginInstances": [{
                "id": "AGI-EXTENSION-" + plugin_id,
                "version": plugin_version
            }]
        }

        card_data = {
            "goal": self.goal,
            "processFlag": "true",
            "plan": json.dumps(plan)
        }

        self.card_instance_id = self.create_and_send_card(self.card_template_id,
                                                          {"flowStatus": AICardStatus.PROCESSING},
                                                          recipients=recipients, support_forward=support_forward)

        self.finish(self.card_instance_id, card_data)
