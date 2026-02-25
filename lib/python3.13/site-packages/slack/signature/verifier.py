import hashlib
import hmac
from time import time
from typing import Dict, Optional, Union


class Clock:
    @staticmethod
    def now() -> float:
        return time()


class SignatureVerifier:
    def __init__(self, signing_secret: str, clock: Clock = Clock()):
        """Slack request signature verifier

        Slack signs its requests using a secret that's unique to your app.
        With the help of signing secrets, your app can more confidently verify
        whether requests from us are authentic.
        https://docs.slack.dev/authentication/verifying-requests-from-slack/
        """
        self.signing_secret = signing_secret
        self.clock = clock

    def is_valid_request(
        self,
        body: Union[str, bytes],
        headers: Dict[str, str],
    ) -> bool:
        """Verifies if the given signature is valid"""
        if headers is None:
            return False
        normalized_headers = {k.lower(): v for k, v in headers.items()}
        return self.is_valid(
            body=body,
            timestamp=normalized_headers.get("x-slack-request-timestamp", None),
            signature=normalized_headers.get("x-slack-signature", None),
        )

    def is_valid(
        self,
        body: Union[str, bytes],
        timestamp: str,
        signature: str,
    ) -> bool:
        """Verifies if the given signature is valid"""
        if timestamp is None or signature is None:
            return False

        if abs(self.clock.now() - int(timestamp)) > 60 * 5:
            return False

        calculated_signature = self.generate_signature(timestamp=timestamp, body=body)
        if calculated_signature is None:
            return False
        return hmac.compare_digest(calculated_signature, signature)

    def generate_signature(self, *, timestamp: str, body: Union[str, bytes]) -> Optional[str]:
        """Generates a signature"""
        if timestamp is None:
            return None
        if body is None:
            body = ""
        if isinstance(body, bytes):
            body = body.decode("utf-8")

        format_req = str.encode(f"v0:{timestamp}:{body}")
        encoded_secret = str.encode(self.signing_secret)
        request_hash = hmac.new(encoded_secret, format_req, hashlib.sha256).hexdigest()
        calculated_signature = f"v0={request_hash}"
        return calculated_signature
