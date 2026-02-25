from datetime import datetime
from typing import Optional, Union

from slack_sdk.models.basic_objects import BaseObject


class Link(BaseObject):
    def __init__(self, *, url: str, text: str):
        """Base class used to generate links in Slack's not-quite Markdown, not quite HTML syntax
        https://docs.slack.dev/messaging/formatting-message-text/#linking_to_urls
        """
        self.url = url
        self.text = text

    def __str__(self):
        if self.text:
            separator = "|"
        else:
            separator = ""
        return f"<{self.url}{separator}{self.text}>"


class DateLink(Link):
    def __init__(
        self,
        *,
        date: Union[datetime, int],
        date_format: str,
        fallback: str,
        link: Optional[str] = None,
    ):
        """Text containing a date or time should display that date in the local timezone of the person seeing the text.
        https://docs.slack.dev/messaging/formatting-message-text/#date-formatting
        """
        if isinstance(date, datetime):
            epoch = int(date.timestamp())
        else:
            epoch = date
        if link is not None:
            link = f"^{link}"
        else:
            link = ""
        super().__init__(url=f"!date^{epoch}^{date_format}{link}", text=fallback)


class ObjectLink(Link):
    prefix_mapping = {
        "C": "#",  # channel
        "G": "#",  # group message
        "U": "@",  # user
        "W": "@",  # workspace user (enterprise)
        "B": "@",  # bot user
        "S": "!subteam^",  # user groups, originally known as subteams
    }

    def __init__(self, *, object_id: str, text: str = ""):
        """Convenience class to create links to specific object types
        https://docs.slack.dev/messaging/formatting-message-text/#linking-channels
        """
        prefix = self.prefix_mapping.get(object_id[0].upper(), "@")
        super().__init__(url=f"{prefix}{object_id}", text=text)


class ChannelLink(Link):
    def __init__(self):
        """Represents an @channel link, which notifies everyone present in this channel.
        https://docs.slack.dev/messaging/formatting-message-text/
        """
        super().__init__(url="!channel", text="channel")


class HereLink(Link):
    def __init__(self):
        """Represents an @here link, which notifies all online users of this channel.
        https://docs.slack.dev/messaging/formatting-message-text/
        """
        super().__init__(url="!here", text="here")


class EveryoneLink(Link):
    def __init__(self):
        """Represents an @everyone link, which notifies all users of this workspace.
        https://docs.slack.dev/messaging/formatting-message-text/
        """
        super().__init__(url="!everyone", text="everyone")
