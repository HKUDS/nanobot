from flask import request, make_response, Response

from lark_oapi.core.const import UTF_8
from lark_oapi.core.model import RawRequest, RawResponse


def parse_req() -> RawRequest:
    headers = {}
    for pair in request.headers.to_wsgi_list():
        headers[pair[0]] = pair[1]

    req = RawRequest()
    req.uri = request.path
    req.body = request.data
    req.headers = headers

    return req


def parse_resp(response: RawResponse) -> Response:
    resp = make_response(str(response.content, UTF_8))
    resp.status_code = response.status_code
    for k, v in response.headers.items():
        resp.headers[k] = v

    return resp
