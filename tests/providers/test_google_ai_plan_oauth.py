"""Public Google AI plan OAuth flow: real loopback and ES256, no live Google calls."""

import base64
import hashlib
import json
import os
import socket
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from nanobot.providers import google_ai_plan_oauth as oauth

QUOTA = "https://www.googleapis.com/auth/generative-language.peruserquota"
TOKEN = "https://oauth2.googleapis.com/token"
CODE = "4/test+single-use-code"
CLIENT = "approved-test-desktop-client"
SECRET = "private-desktop-secret"
PROXY = "http://user:proxy-secret@proxy.invalid:3128"


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sha(value):
    return b64(hashlib.sha256(value.encode()).digest())


def verified_proof(request):
    head, body, sig = request.headers["DPoP"].split(".")
    header, claims, signature = json.loads(unb64(head)), json.loads(unb64(body)), unb64(sig)
    jwk = header["jwk"]
    assert header == {"typ": "dpop+jwt", "alg": "ES256", "jwk": jwk}
    assert jwk.keys() == {"kty", "crv", "x", "y"} and (jwk["kty"], jwk["crv"]) == ("EC", "P-256")
    x, y = (int.from_bytes(unb64(jwk[field]), "big") for field in ("x", "y"))
    assert len(signature) == 64
    der = encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
    ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key().verify(
        der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())
    )
    assert claims["htm"] == request.method == "POST" and claims["htu"] == str(request.url) == TOKEN
    return claims, jwk


def callback(uri, params, *, path=None, host=None):
    address = urlsplit(uri)
    assert address.hostname == "127.0.0.1" and address.port and address.scheme == "http"
    assert address.path == "/oauth2callback"
    connection = HTTPConnection(address.hostname, address.port, timeout=2)
    try:
        connection.request("GET", f"{path or address.path}?{urlencode(params)}", headers={"Host": host or address.netloc})
        response = connection.getresponse()
        assert CODE.encode() not in response.read()
        return response.status
    finally:
        connection.close()


class Google:
    """Script the HTTPS endpoint, capturing the actual form and verifying every proof."""

    def __init__(self):
        self.auth = {}
        self.forms = []
        self.proofs = []
        self.keys = []
        self.proxies = []
        self.replies = []
        self.exchange_error = None
        self.ttl = 3600
        self.bad_claims = {}
        self.token_overrides = {}

    def browser(self, url):
        address = urlsplit(url)
        assert address._replace(query="").geturl() == "https://accounts.google.com/o/oauth2/v2/auth"
        self.auth = dict(parse_qsl(address.query))
        assert self.auth["client_id"] == CLIENT and SECRET not in url
        assert self.auth["scope"] == f"openid email profile {QUOTA}"
        assert self.auth["response_type"] == "code" and self.auth["code_challenge_method"] == "S256"
        assert self.auth["nonce"] != self.auth["state"] and len(self.auth["state"]) >= 43
        assert callback(self.auth["redirect_uri"], {"code": CODE, "state": self.auth["state"]}) == 200

    def endpoint(self, request):
        form = dict(parse_qsl(request.content.decode()))
        claims, jwk = verified_proof(request)
        self.forms.append(form)
        self.proofs.append(claims)
        self.keys.append(jwk)
        assert form["client_id"] == CLIENT and form["client_secret"] == SECRET
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        if form["grant_type"] == "refresh_token":
            return self.replies.pop(0)
        assert form["grant_type"] == "authorization_code" and form["code"] == CODE
        assert form["redirect_uri"] == self.auth["redirect_uri"]
        assert sha(form["code_verifier"]) == self.auth["code_challenge"]
        assert claims["jti"] == sha(CODE) and "nonce" not in claims
        assert abs(claims["iat"] - time.time()) < 5
        if self.exchange_error is not None:
            return self.exchange_error
        identity = {"aud": CLIENT, "iss": "https://accounts.google.com", "exp": int(time.time()) + 600,
                    "nonce": self.auth["nonce"], **self.bad_claims}
        id_token = "mock." + b64(json.dumps(identity).encode()) + ".mock"
        return httpx.Response(200, headers={"DPoP-Nonce": "exchange-only"}, json={
            "access_token": "first-access", "refresh_token": "first-refresh", "expires_in": self.ttl,
            "scope": QUOTA, "id_token": id_token, **self.token_overrides,
        })


@pytest.fixture
def google(monkeypatch, tmp_path):
    service = Google()
    monkeypatch.setattr(oauth, "get_config_path", lambda: tmp_path / "profile" / "config.json")
    monkeypatch.setenv("NANOBOT_GOOGLE_AI_PLAN_CLIENT_ID", CLIENT)
    monkeypatch.setenv("NANOBOT_GOOGLE_AI_PLAN_CLIENT_SECRET", SECRET)
    real_client = httpx.Client

    def client(*, proxy, trust_env, follow_redirects, timeout):
        assert trust_env is follow_redirects is False
        service.proxies.append(proxy)
        return real_client(transport=httpx.MockTransport(service.endpoint), trust_env=False, timeout=timeout)

    monkeypatch.setattr(oauth.httpx, "Client", client)
    return service


def test_profile_login_cached_access_and_local_logout(google, tmp_path, monkeypatch):
    assert not oauth.has_google_ai_plan_login() and not oauth.logout_google_ai_plan()
    oauth.login_google_ai_plan(on_url=google.browser, proxy=PROXY)
    path, = (tmp_path / "profile").rglob("*.json")
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not any(value in path.read_text() for value in (SECRET, CODE, "exchange-only", "id_token", PROXY))
    monkeypatch.delenv("NANOBOT_GOOGLE_AI_PLAN_CLIENT_SECRET")
    assert oauth.has_google_ai_plan_login() and oauth.get_google_ai_plan_token() == "first-access"
    with monkeypatch.context() as m:
        m.setattr(oauth, "get_config_path", lambda: tmp_path / "another-profile" / "config.json")
        assert not oauth.has_google_ai_plan_login() and not oauth.logout_google_ai_plan()
    assert oauth.logout_google_ai_plan() and not path.exists() and not oauth.has_google_ai_plan_login()
    with pytest.raises(oauth.GoogleAIPlanOAuthError, match="Sign in again"):
        oauth.get_google_ai_plan_token()
    assert google.proxies == [PROXY]


def test_exchange_does_not_replay_code_and_new_login_gets_new_key(google):
    google.exchange_error = httpx.Response(400, headers={"DPoP-Nonce": "ignore"},
                                          json={"error": "use_dpop_nonce", "error_description": CODE})
    with pytest.raises(oauth.GoogleAIPlanOAuthError, match="HTTP 400") as error:
        oauth.login_google_ai_plan(on_url=google.browser)
    assert len(google.forms) == 1 and not oauth.has_google_ai_plan_login() and CODE not in str(error.value)
    first_auth = google.auth
    google.exchange_error = None
    oauth.login_google_ai_plan(on_url=google.browser)
    assert google.keys[0] != google.keys[1]
    assert all(first_auth[name] != google.auth[name] for name in ("state", "nonce", "code_challenge"))


@pytest.mark.parametrize("first", ["nonce", "clock"])
def test_refresh_challenges_rotation_and_reuse(google, first):
    google.ttl = 280  # Not expired yet, but inside Google's five-minute refresh margin.
    oauth.login_google_ai_plan(on_url=google.browser)
    clock = httpx.Response(400, headers={"Date": "Wed, 25 Nov 2026 12:00:00 GMT"}, json={"error": "invalid_dpop_proof"})
    nonce = httpx.Response(400, headers={"DPoP-Nonce": "challenge"}, json={"error": "use_dpop_nonce"})
    google.replies = [nonce, clock] if first == "nonce" else [clock, nonce]
    google.replies += [
        httpx.Response(200, json={"access_token": "short", "refresh_token": "rotated", "expires_in": 90}),
        httpx.Response(200, headers={"DPoP-Nonce": "latest"}, json={"access_token": "short2", "expires_in": 60}),
        httpx.Response(200, json={"access_token": "final"}),
    ]
    assert oauth.get_google_ai_plan_token(proxy=PROXY) == "short"
    p0, p1, p2 = google.proofs[1:]
    assert "nonce" not in p0  # Never reuse the code exchange nonce.
    assert p1.get("nonce") == ("challenge" if first == "nonce" else None)
    assert p2["iat"] == 1795608000 and p2["nonce"] == "challenge"
    assert oauth.get_google_ai_plan_token(proxy=PROXY) == "short2"
    # Parallel workers must reread the new token instead of spending the refresh token twice.
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(lambda _: oauth.get_google_ai_plan_token(proxy=PROXY), range(3))) == ["final"] * 3
    assert [p["nonce"] for p in google.proofs[-2:]] == ["challenge", "latest"]
    assert [f["refresh_token"] for f in google.forms[1:]] == ["first-refresh"] * 3 + ["rotated"] * 2
    assert google.keys == [google.keys[0]] * 6 and len({p["jti"] for p in google.proofs}) == 6
    assert google.proxies == [None, PROXY, PROXY, PROXY]


@pytest.mark.parametrize(("claims", "tokens", "message"), [
    ({"nonce": "another-login"}, {}, "invalid ID token"),
    ({"aud": "another-client"}, {}, "invalid ID token"),
    ({"iss": "https://another-issuer.invalid"}, {}, "invalid ID token"),
    ({"exp": 0}, {}, "invalid ID token"),
    ({}, {"id_token": None}, "invalid ID token"),
    ({}, {"scope": f"{QUOTA}.other"}, "did not grant"),
    ({}, {"refresh_token": None}, "no refresh token"),
])
def test_invalid_exchange_never_commits(google, claims, tokens, message):
    google.bad_claims, google.token_overrides = claims, tokens
    with pytest.raises(oauth.GoogleAIPlanOAuthError, match=message):
        oauth.login_google_ai_plan(on_url=google.browser)
    assert not oauth.has_google_ai_plan_login()


def test_callback_rejects_other_hosts_paths_and_unbound_results(google, capsys):
    def browser(url):
        query = dict(parse_qsl(urlsplit(url).query))
        uri, state = query["redirect_uri"], query["state"]
        valid = {"state": state, "code": CODE}
        assert callback(uri, valid, host="attacker.invalid") == 404
        assert callback(uri, valid, path="/other") == 404
        for params in ({"code": CODE}, {"state": "wrong", "error": "access_denied"},
                       [("state", "wrong"), ("state", state), ("code", CODE)]):
            assert callback(uri, params) == 400
        google.browser(url)

    oauth.login_google_ai_plan(on_url=browser)
    assert len(google.forms) == 1 and oauth.has_google_ai_plan_login()
    assert not capsys.readouterr().err  # BaseHTTPRequestHandler must not log request lines.


def test_timeout_closes_loopback_without_exchange(google, monkeypatch):
    monkeypatch.setattr(oauth, "_CALLBACK_TIMEOUT", 0.05)
    urls = []
    with pytest.raises(oauth.GoogleAIPlanOAuthError, match="timed out"):
        oauth.login_google_ai_plan(on_url=urls.append)
    redirect = urlsplit(dict(parse_qsl(urlsplit(urls[0]).query))["redirect_uri"])
    with pytest.raises(OSError):
        socket.create_connection((redirect.hostname, redirect.port), timeout=1)
    assert not google.forms and not oauth.has_google_ai_plan_login()


def test_denial_does_not_echo_query_or_replace_login(google):
    oauth.login_google_ai_plan(on_url=google.browser)

    def deny(url):
        q = dict(parse_qsl(urlsplit(url).query))
        assert callback(q["redirect_uri"], {"state": q["state"], "error": CODE, "error_description": SECRET}) == 400

    with pytest.raises(oauth.GoogleAIPlanOAuthError, match="denied") as error:
        oauth.login_google_ai_plan(on_url=deny)
    assert CODE not in str(error.value) and SECRET not in str(error.value)
    assert len(google.forms) == 1 and oauth.get_google_ai_plan_token() == "first-access"


@pytest.mark.parametrize("variable", ["NANOBOT_GOOGLE_AI_PLAN_CLIENT_ID", "NANOBOT_GOOGLE_AI_PLAN_CLIENT_SECRET"])
def test_no_fallback_desktop_client(google, variable, monkeypatch):
    monkeypatch.delenv(variable)
    with pytest.raises(oauth.GoogleAIPlanOAuthError, match=variable):
        oauth.login_google_ai_plan(on_url=lambda _: pytest.fail("opened consent without client"))
    assert not google.forms


@pytest.mark.parametrize("kind,expected", [("invalid_grant", "Sign in again"), ("unauthorized_client", "Sign in again"),
                                           ("repeated_nonce", "HTTP 400"), ("repeated_clock", "HTTP 400"),
                                           ("bad_json", "request failed")])
def test_refresh_failure_bounded_and_redacted(google, kind, expected):
    google.ttl = 10
    oauth.login_google_ai_plan(on_url=google.browser)
    if kind == "bad_json":
        google.replies = [httpx.Response(502, text=SECRET)]
    elif kind.startswith("repeated_"):
        code = "use_dpop_nonce" if kind == "repeated_nonce" else "invalid_dpop_proof"
        google.replies = [httpx.Response(400, json={"error": code, "error_description": SECRET},
                                         headers={"DPoP-Nonce": n, "Date": "Wed, 25 Nov 2026 12:00:00 GMT"}) for n in ("a", "b")]
    else:
        google.replies = [httpx.Response(400, json={"error": kind, "error_description": SECRET})]
    with pytest.raises(oauth.GoogleAIPlanOAuthError, match=expected) as error:
        oauth.get_google_ai_plan_token(proxy=PROXY)
    assert not any(s in str(error.value) for s in (CODE, SECRET, PROXY, "first-refresh"))
    assert not google.replies
