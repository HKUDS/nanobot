# -*- coding: utf-8 -*-
from typing import List


class PinsMessage:
    guild_id: str
    channel_id: str
    message_ids: List[str]
