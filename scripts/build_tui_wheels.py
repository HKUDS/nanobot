"""Bundle verified native TUI releases into platform-specific Python wheels.

Run from the release checkout with ``uv run python -m scripts.build_tui_wheels``.
The universal wheel is an intermediate, not a PyPI upload candidate.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import runpy
import stat
import struct
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

# Packaging must use the same archive checks as the installed launcher.
from nanobot.cli.tui_launcher import (
    _verified_release_archive,  # pyright: ignore[reportPrivateUsage]
)
from nanobot.releases import PLATFORMS

ROOT = Path(__file__).resolve().parents[1]


def _digest(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def source_files(raw: bytes) -> dict[str, bytes]:
    """Compare archive contents without extracting any untrusted path to disk."""
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive:
            if member.isdir():
                continue
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or member.name in files or not 0 <= member.size <= 20 * 1024 * 1024):
                raise ValueError(f"Invalid TUI source entry: {member.name}")
            stream = archive.extractfile(member)
            assert stream is not None
            files[member.name] = stream.read()
    return files


def _verify_architecture(binary: bytes, target: str) -> None:
    if target.startswith("linux-"):
        machine = 183 if target.endswith("arm64") else 62
        valid = (binary[:6] == b"\x7fELF\x02\x01" and len(binary) >= 20
                 and struct.unpack_from("<H", binary, 18)[0] == machine)
    elif target.startswith("darwin-"):
        cpu = 0x0100000C if target.endswith("arm64") else 0x01000007
        valid = (binary[:4] == b"\xcf\xfa\xed\xfe" and len(binary) >= 8
                 and struct.unpack_from("<I", binary, 4)[0] == cpu)
    else:
        offset = struct.unpack_from("<I", binary, 60)[0] if len(binary) >= 64 else len(binary)
        valid = (binary[:2] == b"MZ" and len(binary) >= offset + 6
                 and binary[offset:offset + 6] == b"PE\x00\x00\x64\x86")
    if not valid:
        raise ValueError(f"TUI executable architecture does not match {target}")


def wheel_files(wheel: Path, version: str, *, platform: str = "any") -> tuple[dict[str, bytes], dict[str, int], str]:
    """Verify identity and every RECORD entry for an intermediate or final wheel."""
    prefix = f"nanobot_ai-{version}"
    if wheel.name != f"{prefix}-py3-none-{platform}.whl":
        kind = "universal wheel" if platform == "any" else "platform wheel"
        raise ValueError(f"Expected the candidate's {kind} ({version})")
    info_dir = f"{prefix}.dist-info"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate wheel entries")
        for name in names:
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or "\\" in name
                    or (platform == "any" and name.startswith("nanobot/tui/bin/"))
                    or name.endswith(("/RECORD.jws", "/RECORD.p7s"))):
                raise ValueError(f"Unexpected base wheel entry: {name}")
        files = {name: archive.read(name) for name in names if not name.endswith("/")}
        modes = {name: archive.getinfo(name).external_attr >> 16 for name in files}
    metadata = BytesParser().parsebytes(files[f"{info_dir}/METADATA"])
    wheel_metadata = BytesParser().parsebytes(files[f"{info_dir}/WHEEL"])
    if (metadata["Name"] != "nanobot-ai" or metadata["Version"] != version
            or wheel_metadata["Root-Is-Purelib"] != ("true" if platform == "any" else "false")
            or wheel_metadata.get_all("Tag") != [f"py3-none-{platform}"]):
        raise ValueError("Base wheel metadata does not match the candidate")
    record = f"{info_dir}/RECORD"
    rows = list(csv.reader(io.StringIO(files[record].decode())))
    if len(rows) != len(files) or {row[0] for row in rows} != set(files):
        raise ValueError("Base wheel RECORD does not cover every file exactly once")
    for name, digest, size in rows:
        expected = ("", "") if name == record else (_digest(files[name]), str(len(files[name])))
        if (digest, size) != expected:
            raise ValueError(f"Base wheel RECORD mismatch: {name}")
    return files, modes, info_dir


def release_bundle(tui_dir: Path, target: str, *, root: Path = ROOT) -> dict[str, bytes]:
    """Validate the archive, architecture and corresponding source once at its owner."""
    asset = f"nanobot-tui-{target}" + (".exe" if target.startswith("win32-") else "")
    archive = tui_dir / f"{asset}.zip"
    raw = archive.read_bytes()
    checksum = archive.with_suffix(".zip.sha256").read_text().split()
    if checksum != [hashlib.sha256(raw).hexdigest(), archive.name]:
        raise ValueError(f"TUI archive checksum mismatch: {archive.name}")
    bundle = _verified_release_archive(raw, asset)
    _verify_architecture(bundle[asset], target)
    notices = bundle["THIRD_PARTY_NOTICES.txt"].decode()
    if f"Target: {target}\n" not in notices:
        raise ValueError("TUI notices do not match the target")
    source_packager = runpy.run_path(str(root / "tui/scripts/package-release.py"))
    source_packager["_validate_opentui_version"](root / "tui", notices)
    expected_source = source_packager["_source_archive"](root / "tui")
    if source_files(bundle["nanobot-tui-source.tar.gz"]) != source_files(expected_source):
        raise ValueError("TUI archive source does not match this release checkout; rebuild it")
    return bundle


def build_wheel(wheel: Path, tui_dir: Path, out_dir: Path, target: str, *,
                root: Path = ROOT) -> Path:
    """Fail closed on stale sources, damaged archives, or existing output files."""
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    tag = f"py3-none-{PLATFORMS[target]}"
    output = out_dir / f"nanobot_ai-{version}-{tag}.whl"
    if output.exists():
        raise FileExistsError(output)
    files, modes, info_dir = wheel_files(wheel, version)
    asset = f"nanobot-tui-{target}" + (".exe" if target.startswith("win32-") else "")
    bundle = release_bundle(tui_dir, target, root=root)
    for name, content in bundle.items():
        path = f"nanobot/tui/bin/{name}"
        files[path] = content
        modes[path] = stat.S_IFREG | (0o755 if name == asset else 0o644)
    metadata = BytesParser().parsebytes(files[f"{info_dir}/WHEEL"])
    metadata.replace_header("Root-Is-Purelib", "false")
    metadata.replace_header("Tag", tag)
    files[f"{info_dir}/WHEEL"] = metadata.as_bytes()
    record = f"{info_dir}/RECORD"
    rows = io.StringIO(newline="")
    writer = csv.writer(rows, lineterminator="\n")
    for name, content in sorted(files.items()):
        if name != record:
            writer.writerow((name, _digest(content), len(content)))
    writer.writerow((record, "", ""))
    files[record] = rows.getvalue().encode()
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".tui-wheel-", dir=out_dir) as temporary:
        candidate = Path(temporary) / output.name
        with zipfile.ZipFile(candidate, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as result:
            for name, content in sorted(files.items()):
                entry = zipfile.ZipInfo(name, date_time=(2020, 2, 2, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (modes.get(name, stat.S_IFREG | 0o644) or 0o100644) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                result.writestr(entry, content)
        # Exclusive creation: a second invocation must not replace an accepted candidate.
        output.hardlink_to(candidate)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--tui-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--target", choices=PLATFORMS)
    args = parser.parse_args()
    for target in [args.target] if args.target else PLATFORMS:
        result = build_wheel(args.wheel, args.tui_dir, args.out_dir, target)
        print(f"{result} ({result.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
