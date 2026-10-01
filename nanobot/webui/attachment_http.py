"""Connection-scoped upload capabilities, issued only after the WS handshake."""
from __future__ import annotations

import secrets
from urllib.parse import unquote
from weakref import WeakKeyDictionary

from aiohttp import web
from websockets.asyncio.server import ServerConnection

from nanobot.webui.attachment_store import AttachmentStore, AttachmentUploadError

UPLOAD_PATH = "/api/attachments"


class AttachmentHTTP:
    def __init__(self, store: AttachmentStore) -> None:
        self.store = store
        self._owners: WeakKeyDictionary[ServerConnection, str] = WeakKeyDictionary()
        self._tokens: set[str] = set()

    def issue(self, connection: ServerConnection) -> dict[str, str]:
        self.revoke(connection)
        token = secrets.token_urlsafe(32)
        self._owners[connection] = token
        self._tokens.add(token)
        return {"path": UPLOAD_PATH, "token": token}

    def owner(self, connection: ServerConnection) -> str:
        return self._owners.get(connection, "")

    def revoke(self, connection: ServerConnection) -> None:
        owner = self._owners.pop(connection, "")
        self._tokens.discard(owner)
        if owner:
            self.store.discard_owner(owner)

    async def handle(self, request: web.BaseRequest) -> web.StreamResponse:
        # Never reflect credentials, enable CORS, accept cookies, or reuse the
        # one-shot WS handshake token. The capability is valid on one live WS.
        if request.path != UPLOAD_PATH or request.method != "POST":
            response = web.json_response({"error": "not_found"}, status=404)
        else:
            authorization = request.headers.get("Authorization", "")
            owner = authorization.removeprefix("Bearer ")
            if not authorization.startswith("Bearer ") or owner not in self._tokens:
                response = web.json_response({"error": "unauthorized"}, status=401)
            elif request.headers.get("Content-Encoding") or request.headers.get("Transfer-Encoding"):
                response = web.json_response({"error": "unsupported_framing"}, status=400)
            elif request.headers.get("Expect", "").lower() not in {"", "100-continue"}:
                response = web.json_response({"error": "unsupported_expectation"}, status=417)
            else:
                async def body():
                    # Iteration starts only after metadata and quota validation.
                    if request.headers.get("Expect", "").lower() == "100-continue":
                        await request.writer.write(b"HTTP/1.1 100 Continue\r\n\r\n")
                    async for chunk in request.content.iter_chunked(64 * 1024):
                        yield chunk

                try:
                    reference = await self.store.upload(
                        body(), owner=owner,
                        mime=request.headers.get("Content-Type", ""),
                        size=request.content_length or 0,
                        filename=unquote(request.headers.get("X-Attachment-Name", "")),
                    )
                    if owner not in self._tokens:
                        self.store.discard([reference], owner=owner)
                        raise AttachmentUploadError("Connection closed during upload")
                    response = web.json_response({"reference": reference}, status=201)
                except (AttachmentUploadError, TimeoutError, OSError) as exc:
                    response = web.json_response({"error": str(exc)}, status=400)
        response.headers["Cache-Control"] = "no-store"
        # A POST connection cannot later switch to the GET/WS parser. Closing
        # also avoids draining an unauthenticated or rejected large body.
        response.force_close()
        return response
