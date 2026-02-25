from typing import Union, Optional

from slack_sdk.models import JsonObject


class SocketModeResponse:
    envelope_id: str
    payload: Optional[dict]

    def __init__(self, envelope_id: str, payload: Optional[Union[dict, JsonObject, str]] = None):
        self.envelope_id = envelope_id

        if payload is None:
            self.payload = None
        elif isinstance(payload, JsonObject):
            self.payload = payload.to_dict()
        elif isinstance(payload, dict):
            self.payload = payload
        elif isinstance(payload, str):
            self.payload = {"text": payload}
        else:
            raise ValueError(f"Unsupported payload data type ({type(payload)})")

    def to_dict(self) -> dict:
        d = {"envelope_id": self.envelope_id}
        if self.payload is not None:
            d["payload"] = self.payload  # type: ignore[assignment]
        return d
