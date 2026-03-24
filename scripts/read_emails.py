"""
read_emails.py — Read emails from an Outlook folder via COM automation.

Saves per-email metadata text files and attachments into an output directory.
Handles Outlook COM access restrictions gracefully: when sender/to/cc fields
are blocked (com_error -2147467260), writes <UNAVAILABLE: ...> in metadata.

Usage:
    python scripts/read_emails.py --folder "Inbox" --out-dir media/emails
    python scripts/read_emails.py --folder "Carlos.GajardoGonzalez@prattwhitney.com/x.Inbox_copy" --out-dir media/emails --max-emails 50 --unread-only
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path


def _require_win32():
    try:
        import pywintypes  # noqa: F401
        import win32com.client  # noqa: F401
    except ImportError:
        print("ERROR: pywin32 is required. Install with: pip install pywin32", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Safe attribute access helpers
# ---------------------------------------------------------------------------


def safe_get_attr(obj, attr: str, default=None):
    """Return obj.attr, catching com_error and AttributeError."""
    try:
        val = getattr(obj, attr, default)
        return val
    except Exception:  # noqa: BLE001  # crash-barrier: COM attributes can raise anything
        return default


def get_attr_with_error(obj, attr: str):
    """Return (value, error_message). error_message is None on success."""
    try:
        val = getattr(obj, attr)
        return val, None
    except Exception as exc:  # noqa: BLE001  # crash-barrier: COM attributes can raise anything
        return None, str(exc)


# ---------------------------------------------------------------------------
# Sender / recipient helpers with multiple fallbacks
# ---------------------------------------------------------------------------

_PR_SENDER_NAME = "http://schemas.microsoft.com/mapi/proptag/0x0C1A001E"
_PR_SENDER_EMAIL = "http://schemas.microsoft.com/mapi/proptag/0x0C1F001E"
_PR_DISPLAY_TO = "http://schemas.microsoft.com/mapi/proptag/0x0E04001E"
_PR_DISPLAY_CC = "http://schemas.microsoft.com/mapi/proptag/0x0E03001E"
_PR_TRANSPORT_HEADERS = "http://schemas.microsoft.com/mapi/proptag/0x007D001E"


def _safe_property(msg, schema_url: str) -> str | None:
    """Read a MAPI property via PropertyAccessor. Returns None on failure."""
    try:
        pa = msg.PropertyAccessor
        val = pa.GetProperty(schema_url)
        if val and str(val).strip():
            return str(val).strip()
    except Exception:  # noqa: BLE001
        pass
    return None


def _parse_header_field(headers: str, field_name: str) -> str:
    """Extract a single-line RFC 822 header value (handles line continuation)."""
    pattern = rf"^{re.escape(field_name)}:\s*(.+?)(?=\r?\n\S|\r?\n\r?\n|\Z)"
    m = re.search(pattern, headers, re.IGNORECASE | re.DOTALL)
    if m:
        # Collapse folded lines
        value = re.sub(r"\r?\n[ \t]+", " ", m.group(1)).strip()
        return value
    return ""


def get_transport_headers(msg) -> str:
    """Return the raw transport message headers string, or empty string."""
    return _safe_property(msg, _PR_TRANSPORT_HEADERS) or ""


def get_sender_fields(msg) -> tuple[str, str]:
    """
    Return (sender_name, sender_email) trying multiple strategies:
    1. Standard OOM attributes (SenderName, SenderEmailAddress)
    2. MAPI PropertyAccessor proptags
    3. SentOnBehalfOfName / SentOnBehalfOfEmailAddress
    4. AddressEntry on Sender
    5. Transport headers (From:)
    Falls back to '<UNAVAILABLE: reason>' when all strategies fail.
    """
    # Strategy 1: standard OOM
    name, name_err = get_attr_with_error(msg, "SenderName")
    email, email_err = get_attr_with_error(msg, "SenderEmailAddress")
    if name and email:
        return str(name), str(email)

    # Strategy 2: MAPI proptags
    mapi_name = _safe_property(msg, _PR_SENDER_NAME)
    mapi_email = _safe_property(msg, _PR_SENDER_EMAIL)
    if mapi_name or mapi_email:
        return (mapi_name or name or ""), (mapi_email or email or "")

    # Strategy 3: SentOnBehalf
    sob_name = safe_get_attr(msg, "SentOnBehalfOfName")
    sob_email = safe_get_attr(msg, "SentOnBehalfOfEmailAddress") or safe_get_attr(
        msg, "SentOnBehalfOfName"
    )
    if sob_name:
        return str(sob_name), str(sob_email or "")

    # Strategy 4: AddressEntry
    try:
        sender = msg.Sender
        if sender:
            ae_name = safe_get_attr(sender, "Name") or ""
            ae_email = safe_get_attr(sender, "Address") or ""
            if ae_name or ae_email:
                return str(ae_name), str(ae_email)
    except Exception:  # noqa: BLE001
        pass

    # Strategy 5: transport headers
    headers = get_transport_headers(msg)
    if headers:
        from_line = _parse_header_field(headers, "From")
        if from_line:
            # Try to separate display name from angle-bracket address
            m = re.match(r'"?([^"<]+)"?\s*<([^>]+)>', from_line)
            if m:
                return m.group(1).strip(), m.group(2).strip()
            return from_line, from_line

    reason = name_err or email_err or "unknown"
    unavailable = f"<UNAVAILABLE: {reason}>"
    return unavailable, unavailable


def get_recipients_by_type(msg, rtype: int) -> list[str]:
    """
    Return list of recipient display strings for the given OlMailRecipientType value.
    rtype: 1=To, 2=CC, 3=BCC
    """
    recipients: list[str] = []
    try:
        for i in range(1, msg.Recipients.Count + 1):
            r = msg.Recipients.Item(i)
            r_type = safe_get_attr(r, "Type", 0)
            if r_type == rtype:
                name = safe_get_attr(r, "Name", "")
                address = safe_get_attr(r, "Address", "")
                entry = f"{name} <{address}>" if name and address else (name or address)
                if entry:
                    recipients.append(entry)
    except Exception:  # noqa: BLE001
        pass
    return recipients


def get_display_field(msg, attr: str, header_field: str, recipient_type: int) -> str:
    """
    Get a display field (To / CC) via:
    1. Standard OOM attribute
    2. MAPI proptag (PR_DISPLAY_TO / PR_DISPLAY_CC)
    3. Recipients collection
    4. Transport headers
    Returns '<UNAVAILABLE: reason>' if all fail.
    """
    val, err = get_attr_with_error(msg, attr)
    if val and str(val).strip():
        return str(val).strip()

    # MAPI proptag
    proptag = _PR_DISPLAY_TO if recipient_type == 1 else _PR_DISPLAY_CC
    mapi_val = _safe_property(msg, proptag)
    if mapi_val:
        return mapi_val

    # Recipients collection fallback
    rlist = get_recipients_by_type(msg, recipient_type)
    if rlist:
        return "; ".join(rlist)

    # Transport headers
    headers = get_transport_headers(msg)
    if headers:
        h_val = _parse_header_field(headers, header_field)
        if h_val:
            return h_val

    return f"<UNAVAILABLE: {err or 'unknown'}>"


# ---------------------------------------------------------------------------
# Folder navigation
# ---------------------------------------------------------------------------


def get_folder(namespace, folder_path: str):
    """
    Navigate to a folder given a slash-separated path.

    Examples:
        "Inbox"
        "Carlos.GajardoGonzalez@prattwhitney.com/Inbox"
        "Online Archive - Carlos.GajardoGonzalez@prattwhitney.com/Inbox_copy"
    """
    parts = [p.strip() for p in folder_path.split("/") if p.strip()]
    if not parts:
        raise ValueError(f"Invalid folder path: {folder_path!r}")

    # Try each top-level store whose display name starts with / matches parts[0]
    stores = namespace.Stores
    root_folder = None

    for i in range(1, stores.Count + 1):
        store = stores.Item(i)
        store_name = safe_get_attr(store, "DisplayName", "") or ""
        if store_name.lower() == parts[0].lower():
            root_folder = store.GetRootFolder()
            parts = parts[1:]
            break

    if root_folder is None:
        # Fall back: use default store root and treat all parts as subfolders
        root_folder = namespace.GetDefaultFolder(6).Parent  # olFolderInbox parent = account root

    folder = root_folder
    for part in parts:
        found = False
        subfolders = folder.Folders
        for j in range(1, subfolders.Count + 1):
            sf = subfolders.Item(j)
            sf_name = safe_get_attr(sf, "Name", "") or ""
            if sf_name.lower() == part.lower():
                folder = sf
                found = True
                break
        if not found:
            available = []
            try:
                for j in range(1, folder.Folders.Count + 1):
                    available.append(safe_get_attr(folder.Folders.Item(j), "Name", "?"))
            except Exception:  # noqa: BLE001
                pass
            raise FileNotFoundError(
                f"Subfolder '{part}' not found under '{safe_get_attr(folder, 'Name', '?')}'. "
                f"Available: {available}"
            )

    return folder


# ---------------------------------------------------------------------------
# Attachment saving
# ---------------------------------------------------------------------------


def save_attachments(msg, out_dir: Path) -> list[str]:
    """Save all attachments to out_dir. Returns list of saved filenames."""
    saved: list[str] = []
    try:
        count = safe_get_attr(msg, "Attachments", None)
        if count is None:
            return saved
        att_collection = msg.Attachments
        for i in range(1, att_collection.Count + 1):
            att = att_collection.Item(i)
            filename = safe_get_attr(att, "FileName", None) or f"attachment_{i}"
            # Sanitize filename
            safe_name = re.sub(r'[<>:"/\\|?*]', "_", str(filename))
            dest = out_dir / safe_name
            try:
                att.SaveAsFile(str(dest.resolve()))
                saved.append(safe_name)
            except Exception as exc:  # noqa: BLE001
                saved.append(f"<FAILED: {safe_name} — {exc}>")
    except Exception:  # noqa: BLE001
        pass
    return saved


# ---------------------------------------------------------------------------
# Per-email processing
# ---------------------------------------------------------------------------


def _safe_subject(msg) -> str:
    subj, _ = get_attr_with_error(msg, "Subject")
    if subj:
        return re.sub(r'[<>:"/\\|?*\r\n]', "_", str(subj).strip())[:80]
    return "no_subject"


def _safe_received_time(msg) -> datetime | None:
    t, _ = get_attr_with_error(msg, "ReceivedTime")
    if t:
        try:
            return t  # already a datetime-like from COM
        except Exception:  # noqa: BLE001
            pass
    return None


def process_email(msg, out_dir: Path, index: int) -> dict:
    """Process one MailItem: write metadata file + save attachments."""
    subject = _safe_subject(msg)
    received = _safe_received_time(msg)
    received_str = received.strftime("%Y%m%dT%H%M%S") if received else "unknown_time"

    # Keep folder name short to avoid Windows 260-char path limit for attachments
    short_subject = subject[:40].rstrip()
    folder_name = f"{index:04d}_{received_str}_{short_subject}"
    email_dir = out_dir / folder_name
    email_dir.mkdir(parents=True, exist_ok=True)

    sender_name, sender_email = get_sender_fields(msg)
    to_field = get_display_field(msg, "To", "To", 1)
    cc_field = get_display_field(msg, "CC", "CC", 2)

    body, body_err = get_attr_with_error(msg, "Body")
    body_text = str(body) if body else f"<UNAVAILABLE: {body_err or 'unknown'}>"

    unread = safe_get_attr(msg, "UnRead", None)
    msg_class = safe_get_attr(msg, "MessageClass", "")
    size = safe_get_attr(msg, "Size", None)
    entry_id = safe_get_attr(msg, "EntryID", "")

    # Attachments
    attachments = save_attachments(msg, email_dir)

    # Metadata file
    meta_path = email_dir / "email_meta.txt"
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"Subject:      {_safe_subject(msg)}\n")
        f.write(f"Received:     {received}\n")
        f.write(f"From (name):  {sender_name}\n")
        f.write(f"From (email): {sender_email}\n")
        f.write(f"To:           {to_field}\n")
        f.write(f"CC:           {cc_field}\n")
        f.write(f"Unread:       {unread}\n")
        f.write(f"Class:        {msg_class}\n")
        f.write(f"Size:         {size}\n")
        f.write(f"EntryID:      {entry_id}\n")
        f.write(f"Attachments:  {', '.join(attachments) if attachments else 'none'}\n")
        f.write("\n--- BODY ---\n\n")
        f.write(body_text)

    return {
        "index": index,
        "folder": str(email_dir),
        "subject": subject,
        "received": str(received),
        "sender_name": sender_name,
        "sender_email": sender_email,
        "to": to_field,
        "cc": cc_field,
        "attachments": attachments,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read emails from an Outlook folder and save metadata + attachments."
    )
    p.add_argument(
        "--folder",
        default="Inbox",
        help=(
            "Folder path, slash-separated. Examples:\n"
            "  Inbox\n"
            "  Carlos.GajardoGonzalez@prattwhitney.com/x.Inbox_copy\n"
            "  Online Archive - .../Inbox_copy"
        ),
    )
    p.add_argument(
        "--out-dir",
        default=str(Path.home() / ".nanobot" / "workspace" / "media" / "emails"),
        help="Output directory for per-email subfolders (default: ~/.nanobot/workspace/media/emails)",
    )
    p.add_argument(
        "--max-emails",
        type=int,
        default=0,
        help="Maximum number of emails to process (0 = no limit)",
    )
    p.add_argument(
        "--unread-only",
        action="store_true",
        help="Only process unread emails",
    )
    p.add_argument(
        "--since",
        default="",
        help="Only process emails received on or after this date (YYYY-MM-DD)",
    )
    return p.parse_args()


def main() -> None:
    _require_win32()
    import win32com.client

    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    since_dt: datetime | None = None
    if args.since:
        try:
            since_dt = datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            print(f"ERROR: --since must be YYYY-MM-DD, got: {args.since!r}", file=sys.stderr)
            sys.exit(1)

    print("Connecting to Outlook...")
    outlook = win32com.client.Dispatch("Outlook.Application")
    namespace = outlook.GetNamespace("MAPI")
    namespace.Logon()

    print(f"Navigating to folder: {args.folder}")
    try:
        folder = get_folder(namespace, args.folder)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    folder_name = safe_get_attr(folder, "Name", args.folder)
    items = folder.Items
    total = safe_get_attr(items, "Count", 0) or 0
    print(f"Folder '{folder_name}' contains {total} item(s).")

    # Sort by ReceivedTime descending so newest appear first
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:  # noqa: BLE001
        pass

    processed = 0
    skipped = 0
    errors = 0

    for i in range(1, total + 1):
        if args.max_emails and processed >= args.max_emails:
            break

        try:
            msg = items.Item(i)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}] Could not retrieve item: {exc}")
            errors += 1
            continue

        msg_class = safe_get_attr(msg, "MessageClass", "") or ""
        if not msg_class.startswith("IPM.Note"):
            skipped += 1
            continue

        if args.unread_only:
            unread = safe_get_attr(msg, "UnRead", False)
            if not unread:
                skipped += 1
                continue

        if since_dt:
            received = _safe_received_time(msg)
            if received:
                # Outlook COM returns timezone-aware datetime; compare naive
                received_naive = (
                    received.replace(tzinfo=None) if hasattr(received, "tzinfo") else received
                )
                if received_naive < since_dt:
                    skipped += 1
                    continue

        try:
            result = process_email(msg, out_dir, processed + 1)
            print(
                f"  [{processed + 1:04d}] {result['received']} | "
                f"{result['sender_name']} | {result['subject'][:50]}"
            )
            processed += 1
        except Exception as exc:  # noqa: BLE001  # crash-barrier: per-email errors must not stop the loop
            print(f"  [{i}] ERROR processing email: {exc}")
            errors += 1

    print(f"\nDone. processed={processed}, skipped={skipped}, errors={errors}")
    print(f"Output directory: {out_dir}")


if __name__ == "__main__":
    main()
