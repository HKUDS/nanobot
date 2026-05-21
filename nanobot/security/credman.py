"""Windows Credential Manager integration for storing and retrieving secrets.

Provides ctypes-based bindings to ``CredWriteW`` / ``CredReadW`` so that a
future PR can wire this into the config loader for API key storage.

All functionality is gated behind ``sys.platform == "win32"`` — on other
platforms every public method raises ``NotImplementedError``.
"""

import sys
from typing import Any

if sys.platform == "win32":
    import ctypes
    from ctypes import (
        POINTER,
        Structure,
        byref,
        c_bool,
        c_char,
        c_uint,
        c_ulong,
        c_void_p,
        c_wchar_p,
    )

    class _CREDENTIALW(Structure):
        _fields_: list[tuple[str, Any]] = [
            ("Flags", c_uint),
            ("Type", c_uint),
            ("TargetName", c_wchar_p),
            ("Comment", c_wchar_p),
            ("LastWritten", c_ulong * 2),  # FILETIME
            ("CredentialBlobSize", c_uint),
            ("CredentialBlob", POINTER(c_char)),
            ("Persist", c_uint),
            ("AttributeCount", c_uint),
            ("Attributes", c_void_p),  # PCREDENTIAL_ATTRIBUTEW
            ("TargetAlias", c_wchar_p),
            ("UserName", c_wchar_p),
        ]

    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2

    _kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    _advapi32 = ctypes.windll.advapi32  # type: ignore[attr-defined]

    _advapi32.CredWriteW.argtypes = [POINTER(_CREDENTIALW), c_ulong]
    _advapi32.CredWriteW.restype = c_bool

    _advapi32.CredReadW.argtypes = [c_wchar_p, c_uint, c_ulong, POINTER(POINTER(_CREDENTIALW))]
    _advapi32.CredReadW.restype = c_bool

    _advapi32.CredFree.argtypes = [ctypes.c_void_p]
    _advapi32.CredFree.restype = None


class WindowsCredmanProvider:
    """Store and retrieve secrets from the Windows Credential Manager.

    Usage::

        provider = WindowsCredmanProvider()
        provider.store_secret("nanobot/openrouter", "sk-or-v1-...")
        key = provider.get_secret("nanobot/openrouter")
    """

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise NotImplementedError(
                "Windows Credential Manager is only available on Windows"
            )

    def store_secret(self, name: str, value: str) -> None:
        """Write a generic credential to the Windows Credential Manager.

        Parameters
        ----------
        name:
            Target name for the credential (e.g. ``"nanobot/openrouter"``).
        value:
            The secret string to store.
        """
        if sys.platform != "win32":
            raise NotImplementedError("Windows Credential Manager is only available on Windows")

        blob = value.encode("utf-16-le")
        blob_size = len(blob)
        cred = _CREDENTIALW()
        cred.Type = _CRED_TYPE_GENERIC
        cred.TargetName = name
        cred.CredentialBlobSize = blob_size
        cred.CredentialBlob = ctypes.cast(ctypes.create_string_buffer(blob, blob_size), POINTER(c_char))
        cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = None

        if not _advapi32.CredWriteW(byref(cred), 0):
            raise ctypes.WinError()  # type: ignore[attr-defined]

    def get_secret(self, name: str) -> str | None:
        """Read a generic credential from the Windows Credential Manager.

        Parameters
        ----------
        name:
            Target name that was used with :meth:`store_secret`.

        Returns
        -------
        The secret string, or ``None`` if the credential does not exist.
        """
        if sys.platform != "win32":
            raise NotImplementedError("Windows Credential Manager is only available on Windows")

        cred_ptr = POINTER(_CREDENTIALW)()
        if not _advapi32.CredReadW(name, _CRED_TYPE_GENERIC, 0, byref(cred_ptr)):
            # ERROR_NOT_FOUND (1168) means the credential doesn't exist.
            error = ctypes.get_last_error()  # type: ignore[attr-defined]
            if error == 1168:
                return None
            raise ctypes.WinError(error)  # type: ignore[attr-defined]

        try:
            raw = ctypes.string_at(cred_ptr.contents.CredentialBlob, cred_ptr.contents.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            _advapi32.CredFree(cred_ptr)
