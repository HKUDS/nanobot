from typing import Optional


class Strings(object):

    @staticmethod
    def is_not_empty(s: Optional[str]) -> bool:
        return not Strings.is_empty(s)

    @staticmethod
    def is_empty(s: Optional[str]) -> bool:
        return s is None or len(s) == 0
