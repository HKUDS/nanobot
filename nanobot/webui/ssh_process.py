"""Shared SSH errors and owned subprocess shutdown."""

from __future__ import annotations

import asyncio


class RemoteError(Exception):
    """A stable, non-secret error code for the connection UI."""


def ssh_error(stderr: bytes) -> str:
    text = stderr.decode("utf-8", errors="replace").lower()
    if "host identification has changed" in text:
        return "host_key_changed"
    if "host key verification failed" in text or "no ed25519 host key is known" in text:
        return "host_key_unknown"
    if "sudo:" in text:
        return "runtime_user_denied"
    if "unprotected private key file" in text or "bad permissions" in text:
        return "ssh_key_permissions"
    if "agent refused operation" in text or "signing failed" in text:
        return "ssh_agent_refused"
    if "bad configuration option" in text or "terminating, 1 bad configuration" in text:
        return "ssh_config_invalid"
    if "administratively prohibited" in text:
        return "ssh_forwarding_denied"
    if "open failed: connect failed" in text:
        return "remote_unreachable"
    if "too many authentication failures" in text:
        return "ssh_too_many_keys"
    if "permission denied" in text:
        return "ssh_auth_failed"
    if "connection refused" in text:
        return "ssh_refused"
    if "could not resolve hostname" in text:
        return "ssh_host_not_found"
    if "connection closed" in text or "connection reset" in text:
        return "ssh_connection_closed"
    if "python3" in text and "not found" in text:
        return "python_unavailable"
    return "ssh_unreachable"


async def stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
