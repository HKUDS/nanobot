import asyncio
import base64
import http
import random
import time
from urllib.parse import urlparse, parse_qs

import requests
import websockets

from lark_oapi.core.cache import ExpiringCache
from lark_oapi.core.const import UTF_8, FEISHU_DOMAIN
from lark_oapi.core.enum import LogLevel
from lark_oapi.core.json import JSON
from lark_oapi.core.log import logger
from lark_oapi.core.utils import Strings
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.ws.const import *
from lark_oapi.ws.enum import FrameType, MessageType
from lark_oapi.ws.exception import *
from lark_oapi.ws.model import *
from lark_oapi.ws.pb.google.protobuf.internal.containers import RepeatedCompositeFieldContainer
from lark_oapi.ws.pb.pbbp2_pb2 import Frame

try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)


def _get_by_key(headers: RepeatedCompositeFieldContainer, key: str) -> str:
    for header in headers:
        if header.key == key:
            return header.value

    raise HeaderNotFoundException(key)


def _new_ping_frame(service_id: int) -> Frame:
    frame = Frame()
    header = frame.headers.add()
    header.key = HEADER_TYPE
    header.value = MessageType.PING.value
    frame.service = service_id
    frame.method = FrameType.CONTROL.value
    frame.SeqID = 0
    frame.LogID = 0

    return frame


def _ordinal(n: int):
    suffixes = {1: 'st', 2: 'nd', 3: 'rd'}
    if 10 <= n <= 20:
        suffix = 'th'
    else:
        suffix = suffixes.get(n % 10, 'th')
    return str(n) + suffix


async def _select():
    while True:
        await asyncio.sleep(3600)


def _parse_ws_conn_exception(e: websockets.InvalidStatusCode):
    code = e.headers.get(HEADER_HANDSHAKE_STATUS)
    msg = e.headers.get(HEADER_HANDSHAKE_MSG)
    if code is None or msg is None:
        raise e

    code = int(code)
    if code == AUTH_FAILED:
        auth_code = e.headers.get(HEADER_HANDSHAKE_AUTH_ERRCODE)
        if int(auth_code) == EXCEED_CONN_LIMIT:
            raise ClientException(code, msg)
        else:
            raise ServerException(code, msg)
    elif code == FORBIDDEN:
        raise ClientException(code, msg)
    else:
        raise ServerException(code, msg)


class Client(object):
    def __init__(self,
                 app_id: str,
                 app_secret,
                 log_level: LogLevel = LogLevel.INFO,
                 event_handler: EventDispatcherHandler = None,
                 domain: str = FEISHU_DOMAIN,
                 auto_reconnect: bool = True) -> None:
        self._app_id: str = app_id
        self._app_secret: str = app_secret
        self._log_level: LogLevel = log_level
        self._event_handler: EventDispatcherHandler = event_handler
        self._auto_reconnect: bool = auto_reconnect
        self._domain: str = domain
        self._conn: Optional[websockets.WebSocketClientProtocol] = None
        self._conn_url: str = ""
        self._service_id: str = ""
        self._conn_id: str = ""
        self._reconnect_nonce: int = 30
        self._reconnect_count: int = -1
        self._reconnect_interval: int = 120
        self._ping_interval: int = 120
        self._cache: ExpiringCache = ExpiringCache(clear_interval=30)
        self._lock = asyncio.Lock()
        logger.setLevel(log_level.value)

    def start(self) -> None:
        try:
            loop.run_until_complete(self._connect())
        except ClientException as e:
            logger.error(self._fmt_log("connect failed, err: {}", e))
            raise e
        except Exception as e:
            logger.error(self._fmt_log("connect failed, err: {}", e))
            loop.run_until_complete(self._disconnect())
            if self._auto_reconnect:
                loop.run_until_complete(self._reconnect())
            else:
                raise e

        loop.create_task(self._ping_loop())
        loop.run_until_complete(_select())

    async def _ping_loop(self):
        while True:
            try:
                if self._conn is not None:
                    frame = _new_ping_frame(int(self._service_id))
                    await self._write_message(frame.SerializeToString())
                    logger.debug(self._fmt_log("ping success"))
            except Exception as e:
                logger.warn(self._fmt_log("ping failed, err: {}", e))
            finally:
                await asyncio.sleep(self._ping_interval)

    async def _connect(self) -> None:
        await self._lock.acquire()
        if self._conn is not None:
            return
        try:
            conn_url = self._get_conn_url()
            u = urlparse(conn_url)
            q = parse_qs(u.query)
            conn_id = q[DEVICE_ID][0]
            service_id = q[SERVICE_ID][0]

            conn = await websockets.connect(conn_url)
            self._conn = conn
            self._conn_url = conn_url
            self._conn_id = conn_id
            self._service_id = service_id

            logger.info(self._fmt_log("connected to {}", conn_url))
            loop.create_task(self._receive_message_loop())
        except websockets.InvalidStatusCode as e:
            _parse_ws_conn_exception(e)
        finally:
            self._lock.release()

    async def _receive_message_loop(self):
        try:
            while True:
                if self._conn is None:
                    raise ConnectionClosedException("connection is closed")
                msg = await self._conn.recv()
                loop.create_task(self._handle_message(msg))
        except Exception as e:
            logger.error(self._fmt_log("receive message loop exit, err: {}", e))
            await self._disconnect()
            if self._auto_reconnect:
                await self._reconnect()
            else:
                raise e

    def _get_conn_url(self) -> str:
        if Strings.is_empty(self._app_id) or Strings.is_empty(self._app_secret):
            raise ClientException(NO_CREDENTIAL, "app_id or app_secret is null")

        response = requests.post(
            self._domain + GEN_ENDPOINT_URI,
            headers={
                "locale": "zh",
            },
            json={
                "AppID": self._app_id,
                "AppSecret": self._app_secret,
            },
        )
        if response.status_code != http.HTTPStatus.OK:
            raise ServerException(response.status_code, "system busy")

        resp = JSON.unmarshal(str(response.content, UTF_8), EndpointResp)
        if resp.code == OK:
            pass
        elif resp.code == SYSTEM_BUSY:
            raise ServerException(resp.code, "system busy")
        elif resp.code == INTERNAL_ERROR:
            raise ServerException(resp.code, resp.msg)
        else:
            raise ClientException(resp.code, resp.msg)

        data = resp.data
        if data.ClientConfig is not None:
            self._configure(data.ClientConfig)

        return data.URL

    async def _handle_message(self, msg: bytes) -> None:
        try:
            frame = Frame()
            frame.ParseFromString(msg)
            ft = FrameType(frame.method)

            if ft == FrameType.CONTROL:
                await self._handle_control_frame(frame)
            elif ft == FrameType.DATA:
                await self._handle_data_frame(frame)
        except Exception as e:
            logger.error(self._fmt_log("handle message failed, err: {}", e))

    async def _handle_control_frame(self, frame: Frame):
        hs = frame.headers
        type_ = _get_by_key(hs, HEADER_TYPE)
        message_type = MessageType(type_)

        if message_type == MessageType.PING:
            return
        elif message_type == MessageType.PONG:
            logger.debug(self._fmt_log("receive pong"))
            if not frame.payload:
                return
            conf = JSON.unmarshal(str(frame.payload, UTF_8), ClientConfig)
            self._configure(conf)

    async def _handle_data_frame(self, frame: Frame):
        hs = frame.headers
        msg_id = _get_by_key(hs, HEADER_MESSAGE_ID)
        trace_id = _get_by_key(hs, HEADER_TRACE_ID)
        sum_ = _get_by_key(hs, HEADER_SUM)
        seq = _get_by_key(hs, HEADER_SEQ)
        type_ = _get_by_key(hs, HEADER_TYPE)

        pl = frame.payload
        if int(sum_) > 1:
            # 合包
            pl = self._combine(msg_id, int(sum_), int(seq), pl)
            if pl is None:
                return

        message_type = MessageType(type_)
        logger.debug(self._fmt_log("receive message, message_type: {}, message_id: {}, trace_id: {}, payload: {}",
                                   message_type.value, msg_id, trace_id, pl.decode(UTF_8)))

        resp = Response(code=http.HTTPStatus.OK)
        try:
            start = int(round(time.time() * 1000))
            if message_type == MessageType.EVENT:
                result = self._event_handler.do_without_validation(pl)
            elif message_type == MessageType.CARD:
                return
            else:
                return
            end = int(round(time.time() * 1000))
            header = hs.add()
            header.key = HEADER_BIZ_RT
            header.value = str(end - start)
            if result is not None:
                resp.data = base64.b64encode(JSON.marshal(result).encode(UTF_8))
        except Exception as e:
            logger.error(
                self._fmt_log("handle message failed, message_type: {}, message_id: {}, trace_id: {}, err: {}",
                              message_type.value, msg_id, trace_id, e))
            resp = Response(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

        frame.payload = JSON.marshal(resp).encode(UTF_8)
        await self._write_message(frame.SerializeToString())

    async def _reconnect(self):
        # 首次重连随机抖动
        if self._reconnect_nonce > 0:
            nonce = random.random() * self._reconnect_nonce
            await asyncio.sleep(nonce)

        # 重连
        if self._reconnect_count >= 0:
            for i in range(self._reconnect_count):
                if await self._try_connect(i):
                    return
                await asyncio.sleep(self._reconnect_interval)
            raise ServerUnreachableException(
                f"unable to connect to the server after trying {self._reconnect_count} times")
        else:
            i = 0
            while True:
                if await self._try_connect(i):
                    return
                await asyncio.sleep(self._reconnect_interval)
                i += 1

    async def _try_connect(self, cnt: int) -> bool:
        logger.info(self._fmt_log("trying to reconnect for the {} time", _ordinal(cnt + 1)))
        try:
            await self._connect()
            return True
        except ClientException as e:
            logger.error(self._fmt_log("connect failed, err: {}", e))
            raise e
        except Exception as e:
            logger.error(self._fmt_log("connect failed, err: {}", e))
            return False

    async def _disconnect(self):
        try:
            await self._lock.acquire()
            if self._conn is None:
                return
            await self._conn.close()
            logger.info(self._fmt_log("disconnected to {}", self._conn_url))
        finally:
            self._conn = None
            self._conn_url = ""
            self._conn_id = ""
            self._service_id = ""
            self._lock.release()

    async def _write_message(self, data: bytes):
        async with self._lock:
            if self._conn is None:
                raise ConnectionClosedException("connection is closed, write message failed")
            await self._conn.send(data)

    def _combine(self, msg_id: str, sum_: int, seq: int, bs: bytes) -> Optional[bytes]:
        val = self._cache.get(msg_id)
        if val is None:
            buf = [b''] * sum_
            buf[seq] = bs
            self._cache.set(msg_id, buf, 5)
            return None

        val[seq] = bs
        pl = b''
        for v in val:
            if not v:
                self._cache.set(msg_id, val, 5)
                return None
            pl += v

        return pl

    def _configure(self, conf: ClientConfig) -> None:
        self._reconnect_count = conf.ReconnectCount
        self._reconnect_interval = conf.ReconnectInterval
        self._reconnect_nonce = conf.ReconnectNonce
        self._ping_interval = conf.PingInterval

    def _fmt_log(self, fmt: str, *args) -> str:
        log = fmt.format(*args)
        if self._conn_id != "":
            log += f' [conn_id={self._conn_id}]'

        return log
