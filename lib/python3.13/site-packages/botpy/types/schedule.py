# -*- coding: utf-8 -*-
from typing import Literal

from botpy.types.user import Member

RemindType = Literal[0, 1, 2, 3, 4, 5]


class Schedule:
    """
    RemindType
        提醒类型 id	描述
        0	不提醒
        1	开始时提醒
        2	开始前 5 分钟提醒
        3	开始前 15 分钟提醒
        4	开始前 30 分钟提醒
        5	开始前 60 分钟提醒
    """

    id: str
    name: str
    description: str
    start_timestamp: str
    end_timestamp: str
    creator: Member
    jump_channel_id: str
    remind_type: RemindType
