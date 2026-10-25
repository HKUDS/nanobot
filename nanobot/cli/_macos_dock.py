"""Windowless AppKit helper. Run as an isolated stdlib-only script, not an agent.

Only the parent launcher can pass the listening socket. Its private connections
contain browser URLs and act as lifetime leases; no configuration is persisted.
AppKit stays on the main thread. The socket thread sleeps in select, not a GUI
polling loop, and EOF from every launcher removes the icon.
"""

from __future__ import annotations

import ctypes as c
import ipaddress
import selectors
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def is_local_browser_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        local = parts.hostname == "localhost" or ipaddress.ip_address(parts.hostname or "").is_loopback
        return (parts.scheme == "http" and local and parts.port is not None
                and parts.port > 0 and parts.username is None and parts.password is None
                and not any(ord(char) < 32 or ord(char) == 127 for char in url))
    except ValueError:
        return False


class _Clients:
    def __init__(self) -> None:
        self.urls: dict[socket.socket, str] = {}
        self.lock = threading.Lock()

    def current_url(self) -> str | None:
        with self.lock:
            return next(reversed(self.urls.values()), None)

    def add(self, connection: socket.socket, url: str) -> None:
        with self.lock:
            self.urls[connection] = url

    def remove(self, connection: socket.socket) -> None:
        with self.lock:
            self.urls.pop(connection, None)


def _serve(listener: socket.socket, address: Path, clients: _Clients, stop: Callable[[], None]) -> None:
    import fcntl

    listener.setblocking(False)
    with selectors.DefaultSelector() as selector, (address.parent / "start.lock").open("a") as lock:
        selector.register(listener, selectors.EVENT_READ)

        def accept() -> None:
            connection, _ = listener.accept()
            connection.settimeout(0.5)
            try:
                with connection.makefile("rb") as stream:
                    line = stream.readline(8193)
                if not line.endswith(b"\n") or len(line) > 8192:
                    raise ValueError("Invalid Dock request")
                url = line[:-1].decode("utf-8")
                if not is_local_browser_url(url):
                    raise ValueError("Invalid Dock URL")
                clients.add(connection, url)
                selector.register(connection, selectors.EVENT_READ)
                connection.sendall(b"1")
                connection.setblocking(False)
            except (OSError, ValueError):
                clients.remove(connection)
                try:
                    selector.unregister(connection)
                except KeyError:
                    pass
                connection.close()

        try:
            while True:
                for key, _ in selector.select(timeout=None if clients.current_url() else 0.1):
                    connection = key.fileobj
                    if connection is listener:
                        accept()
                    elif isinstance(connection, socket.socket):
                        # No commands after the initial URL. EOF (including SIGKILL)
                        # releases only this launcher's presence, never the gateway.
                        selector.unregister(connection)
                        clients.remove(connection)
                        connection.close()
                if clients.current_url() is not None:
                    continue
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                try:
                    # Serialize last-client exit against a new launcher's handshake.
                    while True:
                        try:
                            accept()
                        except BlockingIOError:
                            break
                    if clients.current_url() is None:
                        listener.close()
                        address.unlink(missing_ok=True)
                        return
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        finally:
            listener.close()
            stop()


class _AppKit:
    """Small, explicit Objective-C ABI adapter; no third-party bridge or compiler."""

    def __init__(self, icon: Path, clients: _Clients) -> None:
        self.objc = c.CDLL("/usr/lib/libobjc.A.dylib")
        self.framework = c.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
        for name, arguments, result in (
            ("objc_getClass", [c.c_char_p], c.c_void_p),
            ("sel_registerName", [c.c_char_p], c.c_void_p),
            ("objc_allocateClassPair", [c.c_void_p, c.c_char_p, c.c_size_t], c.c_void_p),
            ("class_addMethod", [c.c_void_p, c.c_void_p, c.c_void_p, c.c_char_p], c.c_bool),
            ("objc_registerClassPair", [c.c_void_p], None),
        ):
            function = getattr(self.objc, name)
            function.argtypes = arguments
            function.restype = result
        self.clients = clients
        self.callbacks: list[Any] = []
        self.pool = self.send(self.cls("NSAutoreleasePool"), "new")
        self.app = self.send(self.cls("NSApplication"), "sharedApplication")
        self.send(self.app, "setActivationPolicy:", 0, types=(c.c_long,), result=c.c_bool)
        if self.send(self.app, "activationPolicy", result=c.c_long) != 0:
            raise OSError("No desktop application session")
        image = self.send(self.send(self.cls("NSImage"), "alloc"), "initWithContentsOfFile:",
                          self.string(str(icon)), types=(c.c_void_p,))
        if not image:
            raise OSError("Dock image unavailable")
        self.send(self.app, "setApplicationIconImage:", image, types=(c.c_void_p,), result=None)
        delegate_class = self.objc.objc_allocateClassPair(self.cls("NSObject"), b"NanobotDock", 0)

        def open_page(_self: int, _cmd: int, _sender: int) -> None:
            url = self.clients.current_url()
            if url is None:
                return
            target = self.send(self.cls("NSURL"), "URLWithString:", self.string(url), types=(c.c_void_p,))
            workspace = self.send(self.cls("NSWorkspace"), "sharedWorkspace")
            if not self.send(workspace, "openURL:", target, types=(c.c_void_p,), result=c.c_bool):
                alert = self.send(self.cls("NSAlert"), "new")
                self.send(alert, "setMessageText:", self.string("Could not open the browser"),
                          types=(c.c_void_p,), result=None)
                self.send(alert, "setInformativeText:", self.string("Use the WebUI link in your terminal."),
                          types=(c.c_void_p,), result=None)
                self.send(alert, "runModal", result=c.c_long)

        def reopen(_self: int, _cmd: int, sender: int, _visible: bool) -> bool:
            open_page(_self, _cmd, sender)
            return False

        for selector, callback, signature, result, arguments in (
            ("openPage:", open_page, b"v@:@", None, (c.c_void_p,)),
            ("applicationShouldHandleReopen:hasVisibleWindows:", reopen, b"B@:@B",
             c.c_bool, (c.c_void_p, c.c_bool)),
        ):
            wrapped = c.CFUNCTYPE(result, c.c_void_p, c.c_void_p, *arguments)(callback)
            self.callbacks.append(wrapped)  # Objective-C does not retain Python callbacks.
            if not self.objc.class_addMethod(delegate_class, self.selector(selector),
                                             c.cast(wrapped, c.c_void_p), signature):
                raise OSError("Dock delegate unavailable")
        self.objc.objc_registerClassPair(delegate_class)
        self.delegate = self.send(delegate_class, "new")
        self.send(self.app, "setDelegate:", self.delegate, types=(c.c_void_p,), result=None)
        menu = self.send(self.cls("NSMenu"), "new")
        for title, action, key, target in (
            ("Open nanobot", "openPage:", "o", self.delegate),
            ("Hide Dock Icon", "terminate:", "q", self.app),
        ):
            item = self.send(self.send(self.cls("NSMenuItem"), "alloc"),
                             "initWithTitle:action:keyEquivalent:", self.string(title),
                             self.selector(action), self.string(key),
                             types=(c.c_void_p, c.c_void_p, c.c_void_p))
            self.send(item, "setTarget:", target, types=(c.c_void_p,), result=None)
            self.send(menu, "addItem:", item, types=(c.c_void_p,), result=None)
        root = self.send(self.cls("NSMenuItem"), "new")
        self.send(root, "setSubmenu:", menu, types=(c.c_void_p,), result=None)
        bar = self.send(self.cls("NSMenu"), "new")
        self.send(bar, "addItem:", root, types=(c.c_void_p,), result=None)
        self.send(self.app, "setMainMenu:", bar, types=(c.c_void_p,), result=None)
        self.send(self.app, "finishLaunching", result=None)

    def cls(self, name: str) -> int:
        return self.objc.objc_getClass(name.encode())

    def selector(self, name: str) -> int:
        return self.objc.sel_registerName(name.encode())

    def string(self, value: str) -> int:
        return self.send(self.cls("NSString"), "stringWithUTF8String:", value.encode(), types=(c.c_char_p,))

    def send(self, target: int, selector: str, *args: object,
             types: tuple[Any, ...] = (), result: Any = c.c_void_p) -> Any:
        # Give every objc_msgSend its actual ABI. Its variadic C declaration is
        # not sufficient on Apple Silicon (and pointers must not truncate).
        function = c.CFUNCTYPE(result, c.c_void_p, c.c_void_p, *types)(("objc_msgSend", self.objc))
        return function(target, self.selector(selector), *args)

    def stop(self) -> None:
        pool = self.send(self.cls("NSAutoreleasePool"), "new")
        self.send(self.app, "performSelectorOnMainThread:withObject:waitUntilDone:",
                  self.selector("terminate:"), None, False,
                  types=(c.c_void_p, c.c_void_p, c.c_bool), result=None)
        self.send(pool, "drain", result=None)

    def run(self) -> None:
        self.send(self.app, "run", result=None)


def main() -> None:
    if sys.platform != "darwin" or len(sys.argv) != 4:
        raise SystemExit(64)
    listener = socket.socket(fileno=int(sys.argv[1]))
    if (listener.family != socket.AF_UNIX or listener.type != socket.SOCK_STREAM
            or listener.getsockname() != sys.argv[2]):
        raise SystemExit(64)
    clients = _Clients()
    app = _AppKit(Path(sys.argv[3]), clients)
    threading.Thread(target=_serve, args=(listener, Path(sys.argv[2]), clients, app.stop), daemon=True).start()
    app.run()


if __name__ == "__main__":
    main()
