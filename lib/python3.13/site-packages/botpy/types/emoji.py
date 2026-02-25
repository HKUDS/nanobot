# -*- coding: utf-8 -*-
from typing import Literal, TypedDict

"""
EmojiType
值	描述
1	系统表情
2	emoji表情
"""
EmojiType = Literal[1, 2]


class Emoji(TypedDict):
    id: str
    type: EmojiType
