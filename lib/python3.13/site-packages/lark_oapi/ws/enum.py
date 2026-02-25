from enum import Enum


class FrameType(Enum):
    CONTROL = 0
    DATA = 1


class MessageType(Enum):
    EVENT = "event"
    CARD = "card"
    PING = "ping"
    PONG = "pong"
