import json
from typing import List, NamedTuple

from . import BaseObject


class IDNamePair(NamedTuple):
    """Simple type used to help with unpacking event data"""

    id: str
    name: str


class InteractiveEvent(BaseObject):
    response_url: str
    user: IDNamePair
    team: IDNamePair
    channel: IDNamePair

    raw_event: dict

    def __init__(self, event: dict):
        self.raw_event = event
        self.response_url = event["response_url"]


class MessageInteractiveEvent(InteractiveEvent):
    event_type: str
    message_ts: str
    trigger_id: str
    action_id: str
    block_id: str
    message: dict

    def __init__(self, event: dict):
        """
        Convenience class to parse an interactive message payload from the events API

        Args:
            event: the raw event dictionary
        """
        super().__init__(event)
        self.user = IDNamePair(event["user"]["id"], event["user"]["username"])
        self.team: IDNamePair = IDNamePair(event["team"]["id"], event["team"]["domain"])
        self.channel: IDNamePair = IDNamePair(event["channel"]["id"], event["channel"]["name"])
        self.event_type = event["type"]
        self.message_ts = event["message"]["ts"]
        self.trigger_id = event["trigger_id"]
        # actions payload is an array, but will only have one item (the action
        # actually interacted with)
        action = event["actions"][0]
        self.action_id = action["action_id"]
        self.block_id = action["block_id"]
        if action.get("selected_option"):
            self.value = action["selected_option"]["value"]
        else:
            self.value = action["value"]
        self.message = event["message"]


class DialogInteractiveEvent(InteractiveEvent):
    event_type: str
    submission: dict
    state: dict

    def __init__(self, event: dict):
        """
        Convenience class to parse a dialog interaction payload from the events API

        Args:
            event: the raw event dictionary
        """
        super().__init__(event)
        self.user = IDNamePair(event["user"]["id"], event["user"]["name"])
        self.team = IDNamePair(event["team"]["id"], event["team"]["domain"])
        self.channel = IDNamePair(event["channel"]["id"], event["channel"]["name"])
        self.callback_id = event["callback_id"]
        self.event_type = event["type"]
        self.submission = event["submission"]
        if event["state"]:
            self.state = json.loads(event["state"])
        else:
            self.state = {}

    def require_any(self, requirements: List[str]) -> dict:
        """
        Convenience method to construct the 'errors' response to send directly back to
        the invoking HTTP request

        Args:
          requirements: List of required dialog components, by name
        """
        if any(self.submission.get(requirement, "") for requirement in requirements):  # skipcq: PYL-R1705
            return {}
        else:
            errors = []
            for key in self.submission:
                error_text = "At least one value is required"
                errors.append({"name": key, "error": error_text})
            return {"errors": errors}


class SlashCommandInteractiveEvent(InteractiveEvent):
    trigger_id: str
    command: str
    text: str

    def __init__(self, event: dict):
        """
        Convenience class to parse a slash command payload from the events API

        Args:
            event: the raw event dictionary
        """
        super().__init__(event)
        self.user = IDNamePair(event["user_id"], event["user_name"])
        self.channel = IDNamePair(event["channel_id"], event["channel_name"])
        self.team = IDNamePair(event["team_id"], event["team_domain"])
        self.trigger_id = event["trigger_id"]
        self.command = event["command"]
        self.text = event["text"]

    @staticmethod
    def create_reply(message, ephemeral=False) -> dict:
        """
        Create a reply suitable to send directly back to the invoking HTTP request

        Args:
          message: Text to send
          ephemeral: Whether the response should be limited to a single user, or to
                broadcast the reply (_and_ the user's original invocation) to the
                channel publicly
        """
        if ephemeral:  # skipcq: PYL-R1705
            return {"text": message, "response_type": "ephemeral"}
        else:
            return {"text": message, "response_type": "in_channel"}
