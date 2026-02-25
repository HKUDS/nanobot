from typing import Union, Optional

from slack_sdk.models import JsonObject


class SocketModeRequest:
    type: str
    envelope_id: str
    payload: dict
    accepts_response_payload: bool
    retry_attempt: Optional[int]  # events_api
    retry_reason: Optional[str]  # events_api

    def __init__(
        self,
        type: str,
        envelope_id: str,
        payload: Union[dict, JsonObject, str],
        accepts_response_payload: Optional[bool] = None,
        retry_attempt: Optional[int] = None,
        retry_reason: Optional[str] = None,
    ):
        self.type = type
        self.envelope_id = envelope_id

        if isinstance(payload, JsonObject):
            self.payload = payload.to_dict()
        elif isinstance(payload, dict):
            self.payload = payload
        elif isinstance(payload, str):
            self.payload = {"text": payload}
        else:
            unexpected_payload_type = type(payload)
            raise ValueError(f"Unsupported payload data type ({unexpected_payload_type})")

        self.accepts_response_payload = accepts_response_payload or False
        self.retry_attempt = retry_attempt
        self.retry_reason = retry_reason

    @classmethod
    def from_dict(cls, message: dict) -> Optional["SocketModeRequest"]:
        if all(k in message for k in ("type", "envelope_id", "payload")):
            return SocketModeRequest(
                type=message["type"],
                envelope_id=message["envelope_id"],
                payload=message["payload"],
                accepts_response_payload=message.get("accepts_response_payload") or False,
                retry_attempt=message.get("retry_attempt"),
                retry_reason=message.get("retry_reason"),
            )
        return None

    def to_dict(self) -> dict:
        d = {"envelope_id": self.envelope_id}
        if self.payload is not None:
            d["payload"] = self.payload  # type: ignore[assignment]
        return d
