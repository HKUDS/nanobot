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


def _applescript_string(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _browser_root(url: str) -> str:
    """Use the browser's HTTP origin spelling, but keep path case significant."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{ipaddress.IPv6Address(host).compressed}]"
    authority = host if parts.port == 80 else f"{host}:{parts.port}"
    return parts._replace(netloc=authority, query="", fragment="").geturl().rstrip("/")


def _browser_script(bundle_id: str, url: str) -> str | None:
    """Focus a matching tab without navigating it; errors must not mean absence.

    Only URL properties leave the browser, not page contents. The script returns
    a boolean and never returns URLs, titles, credentials or browser history.
    """
    if bundle_id not in {"com.google.Chrome", "com.apple.Safari"}:
        return None
    quoted_root = _applescript_string(_browser_root(url))
    quoted_url = _applescript_string(url)
    if bundle_id == "com.google.Chrome":
        select_tab = "set active tab index of targetWindow to tabIndex\nset minimized of targetWindow to false"
        create_window = f"set newWindow to make new window\nset URL of active tab of newWindow to {quoted_url}\nset newWindowID to id of newWindow"
    else:
        select_tab = "set current tab of targetWindow to tab tabIndex of targetWindow\nset miniaturized of targetWindow to false"
        create_window = f"make new document with properties {{URL:{quoted_url}}}\nset newWindowID to id of window 1"
    # A repeat variable refers to an item of the live windows list. Activation or
    # deminimization reorders that list, so capture a stable ID before either.
    return f'''with timeout of 15 seconds
considering case
tell application id "{bundle_id}"
    repeat with w in windows
        set tabIndex to 0
        repeat with t in tabs of w
            set tabIndex to tabIndex + 1
            set address to URL of t
            if address is not missing value then
                if address is {quoted_root} or address starts with {quoted_root} & "/" or address starts with {quoted_root} & "?" or address starts with {quoted_root} & "#" then
                    set targetWindowID to id of w
                    set targetWindow to window id targetWindowID
                    activate
                    {select_tab}
                    set index of targetWindow to 1
                    return true
                end if
            end if
        end repeat
    end repeat
    {create_window}
    activate
    set index of window id newWindowID to 1
    return true
end tell
end considering
end timeout'''


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
        self.opening = False
        self.started = False
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
            if not self.started or self.opening or self.clients.current_url() is None:
                return
            # A Dock click can deliver both activation and reopen. Coalesce them
            # on the next run-loop turn, including events from permission dialogs.
            self.opening = True
            self.send(self.delegate, "performSelector:withObject:afterDelay:",
                      self.selector("focusPage:"), None, 0.0,
                      types=(c.c_void_p, c.c_void_p, c.c_double), result=None)

        def focus_page(_self: int, _cmd: int, _sender: int) -> None:
            try:
                url = self.clients.current_url()
                if url is not None:
                    self.focus_browser(url)
            finally:
                self.opening = False

        def reopen(_self: int, _cmd: int, sender: int, _visible: bool) -> bool:
            open_page(_self, _cmd, sender)
            return False

        for selector, callback, signature, result, arguments in (
            ("openPage:", open_page, b"v@:@", None, (c.c_void_p,)),
            ("focusPage:", focus_page, b"v@:@", None, (c.c_void_p,)),
            ("applicationDidBecomeActive:", open_page, b"v@:@", None, (c.c_void_p,)),
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
        self.started = True

    def focus_browser(self, url: str) -> None:
        target = self.send(self.cls("NSURL"), "URLWithString:", self.string(url), types=(c.c_void_p,))
        workspace = self.send(self.cls("NSWorkspace"), "sharedWorkspace")
        application = self.send(workspace, "URLForApplicationToOpenURL:", target, types=(c.c_void_p,))
        bundle = self.send(self.cls("NSBundle"), "bundleWithURL:", application, types=(c.c_void_p,))
        identifier = self.send(bundle, "bundleIdentifier")
        raw = self.send(identifier, "UTF8String", result=c.c_char_p)
        source = _browser_script(raw.decode() if raw else "", url)
        if source is None:
            self.alert("Window reuse needs Chrome or Safari",
                       "Switch to your existing nanobot page, or use Chrome or Safari as your default browser.")
            return
        script = self.send(self.send(self.cls("NSAppleScript"), "alloc"), "initWithSource:",
                           self.string(source), types=(c.c_void_p,))
        error = c.c_void_p()
        try:
            result = self.send(script, "executeAndReturnError:", c.byref(error),
                               types=(c.POINTER(c.c_void_p),))
            if result:
                return
            number = self.send(error.value or 0, "objectForKey:", self.string("NSAppleScriptErrorNumber"),
                               types=(c.c_void_p,))
            if self.send(number, "integerValue", result=c.c_long) == -1743:
                self.alert("Allow nanobot to restore your browser window",
                           "In System Settings → Privacy & Security → Automation, allow browser control for the app that requested it. Then click the cat again. Your existing page is unchanged.")
            else:
                self.alert("Could not restore the browser window",
                           "Check that your browser responds, then click the cat again. No extra page was opened to work around this error.")
        finally:
            self.send(script, "release", result=None)

    def alert(self, title: str, detail: str) -> None:
        alert = self.send(self.cls("NSAlert"), "new")
        try:
            self.send(alert, "setMessageText:", self.string(title), types=(c.c_void_p,), result=None)
            self.send(alert, "setInformativeText:", self.string(detail), types=(c.c_void_p,), result=None)
            self.send(alert, "runModal", result=c.c_long)
        finally:
            self.send(alert, "release", result=None)

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
