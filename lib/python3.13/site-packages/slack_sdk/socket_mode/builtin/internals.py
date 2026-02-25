import errno
import hashlib
import itertools
import os
import random
import socket
from socket import socket as Socket
import ssl
import struct
from base64 import encodebytes, b64encode
from hmac import compare_digest
from logging import Logger
from threading import Lock
from typing import Tuple, Optional, Union, List, Callable, Dict
from urllib.parse import urlparse, unquote

from .frame_header import FrameHeader


def _parse_connect_response(sock: Socket) -> Tuple[Optional[int], str]:
    status = None
    lines = []
    while True:
        line = []
        while True:
            c = sock.recv(1)
            if not c:
                raise ConnectionError("Connection is closed")
            line.append(c)
            if c == b"\n":
                break
        line = b"".join(line).decode("utf-8").strip()  # type: ignore[assignment]
        if line is None or len(line) == 0:
            break
        lines.append(line)
        if not status:
            status_line = line.split(" ", 2)  # type: ignore[attr-defined]
            status = int(status_line[1])
    return status, "\n".join(lines)  # type: ignore[arg-type]


def _use_or_create_ssl_context(ssl_context: Optional[ssl.SSLContext] = None):
    return ssl_context if ssl_context is not None else ssl.create_default_context()


def _establish_new_socket_connection(
    session_id: str,
    server_hostname: str,
    server_port: int,
    logger: Logger,
    sock_send_lock: Lock,
    receive_timeout: float,
    proxy: Optional[str],
    proxy_headers: Optional[Dict[str, str]],
    trace_enabled: bool,
    ssl_context: Optional[ssl.SSLContext] = None,
) -> Union[ssl.SSLSocket, Socket]:
    ssl_context = _use_or_create_ssl_context(ssl_context)

    if proxy is not None:
        parsed_proxy = urlparse(proxy)
        proxy_host, proxy_port = parsed_proxy.hostname, parsed_proxy.port or 80
        sock = socket.create_connection((proxy_host, proxy_port), receive_timeout)
        if hasattr(socket, "TCP_NODELAY"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if hasattr(socket, "SO_KEEPALIVE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        message = [f"CONNECT {server_hostname}:{server_port} HTTP/1.0"]
        if parsed_proxy.username is not None and parsed_proxy.password is not None:
            # In the case where the proxy is "http://{username}:{password}@{hostname}:{port}"
            raw_value = f"{unquote(parsed_proxy.username)}:{unquote(parsed_proxy.password)}"
            auth = b64encode(raw_value.encode("utf-8")).decode("ascii")
            message.append(f"Proxy-Authorization: Basic {auth}")
        if proxy_headers is not None:
            for k, v in proxy_headers.items():
                message.append(f"{k}: {v}")
        message.append("")
        message.append("")
        req: str = "\r\n".join([line.lstrip() for line in message])
        if trace_enabled:
            logger.debug(f"Proxy connect request (session id: {session_id}):\n{req}")
        with sock_send_lock:
            sock.send(req.encode("utf-8"))
        status, text = _parse_connect_response(sock)
        if trace_enabled:
            log_message = f"Proxy connect response (session id: {session_id}):\n{text}"
            logger.debug(log_message)
        if status != 200:
            raise Exception(f"Failed to connect to the proxy (proxy: {proxy}, connect status code: {status})")

        sock = ssl_context.wrap_socket(
            sock,
            do_handshake_on_connect=True,
            suppress_ragged_eofs=True,
            server_hostname=server_hostname,
        )
        return sock

    if server_port != 443:
        # only for library testing
        logger.info(f"Using non-ssl socket to connect ({server_hostname}:{server_port})")
        sock = socket.create_connection((server_hostname, server_port), timeout=3)
        return sock

    sock = socket.create_connection((server_hostname, server_port), receive_timeout)
    sock = ssl_context.wrap_socket(
        sock,
        do_handshake_on_connect=True,
        suppress_ragged_eofs=True,
        server_hostname=server_hostname,
    )
    return sock


def _read_http_response_line(sock: ssl.SSLSocket) -> str:
    cs = []
    while True:
        b: bytes = sock.recv(1)
        if not b:
            raise ConnectionError("Connection is closed")
        c: str = b.decode("utf-8")
        if c == "\r":
            break
        if c != "\n":
            cs.append(c)
    return "".join(cs)


def _parse_handshake_response(sock: ssl.SSLSocket) -> Tuple[Optional[int], dict, str]:
    """Parses the handshake response.

    Args:
        sock: The current active socket

    Returns:
        (http status, headers, whole response as a str)
    """
    lines = []
    status = None
    headers: Dict[str, str] = {}
    while True:
        line = _read_http_response_line(sock)
        if status is None:
            elements = line.split(" ")
            if len(elements) > 2:
                status = int(elements[1])
        else:
            elements = line.split(":")
            if len(elements) == 2:
                headers[elements[0].strip().lower()] = elements[1].strip()
        if line is None or len(line.strip()) == 0:
            break
        lines.append(line)
    text = "\n".join(lines)
    return (status, headers, text)


def _generate_sec_websocket_key() -> str:
    return encodebytes(os.urandom(16)).decode("utf-8").strip()


def _validate_sec_websocket_accept(sec_websocket_key: str, headers: dict) -> bool:
    v = (sec_websocket_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("utf-8")
    expected = encodebytes(hashlib.sha1(v).digest()).decode("utf-8").strip()
    actual = headers.get("sec-websocket-accept", "").strip()
    return compare_digest(expected, actual)


def _to_readable_opcode(opcode: int) -> str:
    if opcode == FrameHeader.OPCODE_CONTINUATION:
        return "continuation"
    if opcode == FrameHeader.OPCODE_TEXT:
        return "text"
    if opcode == FrameHeader.OPCODE_BINARY:
        return "binary"
    if opcode == FrameHeader.OPCODE_CLOSE:
        return "close"
    if opcode == FrameHeader.OPCODE_PING:
        return "ping"
    if opcode == FrameHeader.OPCODE_PONG:
        return "pong"
    return "-"


def _parse_text_payload(data: Optional[bytes], logger: Logger) -> str:
    try:
        if data is not None and isinstance(data, bytes):
            return data.decode("utf-8")
        else:
            return ""
    except UnicodeDecodeError as e:
        logger.debug(f"Failed to parse a payload (data: {data!r}, error: {e})")
        return ""


def _receive_messages(
    sock: ssl.SSLSocket,
    sock_receive_lock: Lock,
    logger: Logger,
    receive_buffer_size: int = 1024,
    all_message_trace_enabled: bool = False,
) -> List[Tuple[Optional[FrameHeader], bytes]]:
    def receive(specific_buffer_size: Optional[int] = None):
        size = specific_buffer_size if specific_buffer_size is not None else receive_buffer_size
        with sock_receive_lock:
            try:
                received_bytes = sock.recv(size)
                if all_message_trace_enabled:
                    if len(received_bytes) > 0:
                        logger.debug(f"Received bytes: {received_bytes!r}")
                return received_bytes
            except OSError as e:
                # For Linux/macOS, errno.EBADF is the expected error for bad connections.
                # The errno.ENOTSOCK can be sent when running on Windows OS.
                if e.errno in (errno.EBADF, errno.ENOTSOCK):
                    # Note that bad connections can be detected by monitoring threads
                    # the Socket Mode client automatically reconnects to a new endpoint later.
                    logger.debug("The connection seems to be already closed.")
                    return bytes()
                raise e

    return _fetch_messages(
        messages=[],
        receive=receive,
        remaining_bytes=None,
        current_mask_key=None,
        current_header=None,
        current_data=bytes(),
        logger=logger,
    )


def _fetch_messages(
    messages: List[Tuple[Optional[FrameHeader], bytes]],
    receive: Callable[[Optional[int]], bytes],  # buffer size
    logger: Logger,
    remaining_bytes: Optional[bytes] = None,
    current_mask_key: Optional[str] = None,
    current_header: Optional[FrameHeader] = None,
    current_data: Optional[bytes] = None,
) -> List[Tuple[Optional[FrameHeader], bytes]]:
    if remaining_bytes is None:
        # Fetch more to complete the current message
        remaining_bytes = receive()  # type: ignore[call-arg]

    if remaining_bytes is None or len(remaining_bytes) == 0:
        # no more bytes
        if current_header is not None:
            _append_message(messages, current_header, current_data)  # type: ignore[arg-type]
        return messages

    if current_header is None:
        # new message
        if len(remaining_bytes) <= 2:
            remaining_bytes += receive()  # type: ignore[call-arg]

        if remaining_bytes[0] == 10:  # \n
            if current_data is not None and len(current_data) >= 0:
                _append_message(messages, current_header, current_data)
            _append_message(messages, None, remaining_bytes[:1])
            remaining_bytes = remaining_bytes[1:]
            if len(remaining_bytes) == 0:
                return messages
            else:
                return _fetch_messages(
                    messages=messages,
                    receive=receive,
                    remaining_bytes=remaining_bytes,
                    logger=logger,
                )

        # https://tools.ietf.org/html/rfc6455#section-5.2
        b1, b2 = remaining_bytes[0], remaining_bytes[1]

        # determine data length and the first index of the data part
        current_data_length: int = b2 & 0b01111111
        idx_after_length_part: int = 2
        if current_data_length == 126:
            if len(remaining_bytes) < 4:
                remaining_bytes += receive(1024)
            current_data_length = struct.unpack("!H", bytes(remaining_bytes[2:4]))[0]
            idx_after_length_part = 4
        elif current_data_length == 127:
            if len(remaining_bytes) < 10:
                remaining_bytes += receive(1024)
            current_data_length = struct.unpack("!Q", bytes(remaining_bytes[2:10]))[0]
            idx_after_length_part = 10

        current_header = FrameHeader(
            fin=b1 & 0b10000000,
            rsv1=b1 & 0b01000000,
            rsv2=b1 & 0b00100000,
            rsv3=b1 & 0b00010000,
            opcode=b1 & 0b00001111,
            masked=b2 & 0b10000000,
            length=current_data_length,
        )
        if current_header.masked > 0:
            if current_mask_key is None:
                idx1, idx2 = idx_after_length_part, idx_after_length_part + 4
                current_mask_key = remaining_bytes[idx1:idx2]  # type: ignore[assignment]
                idx_after_length_part += 4

        start, end = idx_after_length_part, idx_after_length_part + current_data_length
        data_to_append = remaining_bytes[start:end]

        current_data = bytes()
        if current_header.masked > 0:
            for i in range(data_to_append):  # type: ignore[call-overload]
                mask = current_mask_key[i % 4]  # type: ignore[index]
                data_to_append[i] ^= mask  # type: ignore[index]
            current_data += data_to_append
        else:
            current_data += data_to_append
        if len(current_data) == current_data_length:
            _append_message(messages, current_header, current_data)
            remaining_bytes = remaining_bytes[end:]
            if len(remaining_bytes) > 0:
                # continue with the remaining data
                return _fetch_messages(
                    messages=messages,
                    receive=receive,
                    remaining_bytes=remaining_bytes,
                    logger=logger,
                )
            else:
                return messages
        elif len(current_data) < current_data_length:
            # need more bytes to complete this message
            return _fetch_messages(
                messages=messages,
                receive=receive,
                current_mask_key=current_mask_key,
                current_header=current_header,
                current_data=current_data,
                logger=logger,
            )
        else:
            # This pattern is unexpected but set data with the expected length anyway
            _append_message(current_header, current_data[:current_data_length])  # type: ignore[call-arg, arg-type]
            return messages

    # work in progress with the current_header/current_data
    if current_header is not None:
        length_needed = current_header.length - len(current_data)  # type: ignore[arg-type]
        if length_needed > len(remaining_bytes):
            current_data += remaining_bytes  # type: ignore[operator]
            # need more bytes to complete this message
            return _fetch_messages(
                messages=messages,
                receive=receive,
                current_mask_key=current_mask_key,
                current_header=current_header,
                current_data=current_data,
                logger=logger,
            )
        else:
            current_data += remaining_bytes[:length_needed]  # type: ignore[operator]
            _append_message(messages, current_header, current_data)
            remaining_bytes = remaining_bytes[length_needed:]
            if len(remaining_bytes) == 0:
                return messages
            else:
                # continue with the remaining data
                return _fetch_messages(
                    messages=messages,
                    receive=receive,
                    remaining_bytes=remaining_bytes,
                    logger=logger,
                )

    return messages


def _append_message(
    messages: List[Tuple[Optional[FrameHeader], bytes]],
    header: Optional[FrameHeader],
    data: bytes,
) -> None:
    messages.append((header, data))


def _build_data_frame_for_sending(
    payload: Union[str, bytes],
    opcode: int,
    fin: int = 1,
    rsv1: int = 0,
    rsv2: int = 0,
    rsv3: int = 0,
    masked: int = 1,
):
    b1 = fin << 7 | rsv1 << 6 | rsv2 << 5 | rsv3 << 4 | opcode
    header: bytes = bytes([b1])

    original_payload_data: bytes = payload.encode("utf-8") if isinstance(payload, str) else payload
    payload_length = len(original_payload_data)
    if payload_length <= 125:
        b2 = masked << 7 | payload_length
        header += bytes([b2])
    else:
        b2 = masked << 7 | 126
        header += struct.pack("!BH", b2, payload_length)

    mask_key: List[int] = random.choices(range(256), k=4)
    header += bytes(mask_key)

    payload_data: bytes = bytes(byte ^ mask for byte, mask in zip(original_payload_data, itertools.cycle(mask_key)))
    return header + payload_data
