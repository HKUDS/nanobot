from .resource import *


class V1(object):
    def __init__(self, config: Config) -> None:
        self.card: Card = Card(config)
        self.card_element: CardElement = CardElement(config)
