# -*- coding:utf-8 -*-

import json

Card_Callback_Router_Topic = '/v1.0/card/instances/callback'


class CardCallbackMessage(object):

    def __init__(self):
        self.extension = {}
        self.corp_id = ""
        self.space_type = ""
        self.user_id_type = -1
        self.type = "actionCallback"
        self.user_id = ""
        self.content = {}
        self.space_id = ""
        self.card_instance_id = ""

    @classmethod
    def from_dict(cls, d):
        msg = CardCallbackMessage()
        for name, value in d.items():
            if name == 'extension':
                msg.extension = json.loads(value)
            elif name == 'corpId':
                msg.corp_id = value
            elif name == "userId":
                msg.user_id = value
            elif name == 'outTrackId':
                msg.card_instance_id = value
            elif name == "content":
                msg.content = json.loads(value)
        return msg

    def to_dict(self):
        msg = {}
        msg["extension"] = json.dumps(self.extension)
        msg["corpId"] = self.corp_id
        msg["type"] = self.type
        msg["userId"] = self.user_id
        msg["content"] = json.dumps(self.content)
        msg["outTrackId"] = self.card_instance_id
        return msg
