from typing import Optional, Sequence


class AuthorizeUrlGenerator:
    def __init__(
        self,
        *,
        client_id: str,
        redirect_uri: Optional[str] = None,
        scopes: Optional[Sequence[str]] = None,
        user_scopes: Optional[Sequence[str]] = None,
        authorization_url: str = "https://slack.com/oauth/v2/authorize",
    ):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.user_scopes = user_scopes
        self.authorization_url = authorization_url

    def generate(self, state: str, team: Optional[str] = None) -> str:
        scopes = ",".join(self.scopes) if self.scopes else ""
        user_scopes = ",".join(self.user_scopes) if self.user_scopes else ""
        url = (
            f"{self.authorization_url}?"
            f"state={state}&"
            f"client_id={self.client_id}&"
            f"scope={scopes}&"
            f"user_scope={user_scopes}"
        )
        if self.redirect_uri is not None:
            url += f"&redirect_uri={self.redirect_uri}"
        if team is not None:
            url += f"&team={team}"
        return url


class OpenIDConnectAuthorizeUrlGenerator:
    """Refer to https://openid.net/specs/openid-connect-core-1_0.html"""

    def __init__(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scopes: Optional[Sequence[str]] = None,
        authorization_url: str = "https://slack.com/openid/connect/authorize",
    ):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.authorization_url = authorization_url

    def generate(self, state: str, nonce: Optional[str] = None, team: Optional[str] = None) -> str:
        scopes = ",".join(self.scopes) if self.scopes else ""
        url = (
            f"{self.authorization_url}?"
            "response_type=code&"
            f"state={state}&"
            f"client_id={self.client_id}&"
            f"scope={scopes}&"
            f"redirect_uri={self.redirect_uri}"
        )
        if team is not None:
            url += f"&team={team}"
        if nonce is not None:
            url += f"&nonce={nonce}"
        return url
