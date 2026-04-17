"""SkillGuard: security scanner for agent-generated skills."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from loguru import logger


class TrustLevel(str, Enum):
    """Origin-based trust tier for skills."""

    BUILTIN = "builtin"
    HUMAN_CURATED = "human_curated"
    AGENT_CREATED = "agent_created"
    UPLOAD = "upload"

_MAX_FILES = 50
_MAX_TOTAL_SIZE = 1_048_576  # 1 MB
_MAX_SINGLE_FILE_SIZE = 512_000

# Exfiltration: curl/wget piping secrets or env vars to external URLs
_EXFIL_PATTERNS = [
    re.compile(r"(curl|wget|fetch)\s+.*\$\{?\w*(KEY|SECRET|TOKEN|PASS|CRED)", re.IGNORECASE),
    re.compile(r"(curl|wget)\s+.*-d\s+.*\$", re.IGNORECASE),
    re.compile(r"\|\s*(nc|ncat|netcat)\s+", re.IGNORECASE),
]

# Prompt injection
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|above)\s+(instructions?|rules?|prompts?)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an|in)\s+", re.IGNORECASE),
    re.compile(r"disregard\s+(your|all|any)\s+(previous|prior|system)", re.IGNORECASE),
    re.compile(r"new\s+instructions?:\s*", re.IGNORECASE),
    re.compile(r"override\s+(system|safety|security)\s+(prompt|instructions?|rules?)", re.IGNORECASE),
]

# Destructive commands
_DESTRUCTIVE_PATTERNS = [
    re.compile(r"rm\s+-r[fe]*\s+/", re.IGNORECASE),
    re.compile(r":(){ :\|:& };:", re.IGNORECASE),  # fork bomb
    re.compile(r"dd\s+if=.*of=/dev/", re.IGNORECASE),
    re.compile(r"mkfs\.", re.IGNORECASE),
    re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE),
]

# Persistence mechanisms
_PERSISTENCE_PATTERNS = [
    re.compile(r"crontab\s+-", re.IGNORECASE),
    re.compile(r"/etc/cron", re.IGNORECASE),
    re.compile(r"\.bashrc|\.bash_profile|\.profile|\.zshrc", re.IGNORECASE),
    re.compile(r"systemctl\s+(enable|start)", re.IGNORECASE),
    re.compile(r"launchctl\s+load", re.IGNORECASE),
]

# Credential patterns
_CREDENTIAL_PATTERNS = [
    re.compile(r"(api[_-]?key|secret[_-]?key|password|token)\s*[:=]\s*['\"][^'\"]{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", re.IGNORECASE),
    re.compile(r"(aws_access_key_id|aws_secret_access_key)\s*=", re.IGNORECASE),
]

# Invisible unicode
_INVISIBLE_CHARS = re.compile(r"[\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufeff\u00ad]")

_BINARY_EXTENSIONS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o",
    ".pyc", ".pyo", ".class", ".jar", ".war",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".wasm", ".msi", ".dmg", ".iso",
})


@dataclass
class Finding:
    category: str
    severity: str  # "warning" or "danger"
    message: str
    file: str = ""
    line: int = 0


@dataclass
class ScanResult:
    verdict: str = "safe"  # "safe", "caution", "dangerous"
    findings: list[Finding] = field(default_factory=list)


_INSTALL_POLICY: dict[TrustLevel, dict[str, bool]] = {
    TrustLevel.BUILTIN: {"safe": True, "caution": True, "dangerous": True},
    TrustLevel.HUMAN_CURATED: {"safe": True, "caution": True, "dangerous": False},
    TrustLevel.AGENT_CREATED: {"safe": True, "caution": True, "dangerous": False},
    TrustLevel.UPLOAD: {"safe": True, "caution": True, "dangerous": False},
}


class SkillGuard:
    """Scan a skill directory for security threats."""

    def scan_skill(self, skill_dir: Path) -> ScanResult:
        result = ScanResult()

        if not skill_dir.is_dir():
            result.findings.append(Finding(
                category="structural", severity="danger",
                message=f"Skill directory does not exist: {skill_dir}",
            ))
            result.verdict = "dangerous"
            return result

        self._check_structure(skill_dir, result)
        self._check_content(skill_dir, result)

        if any(f.severity == "danger" for f in result.findings):
            result.verdict = "dangerous"
        elif result.findings:
            result.verdict = "caution"
        return result

    def should_allow(
        self,
        result: ScanResult,
        trust: TrustLevel = TrustLevel.AGENT_CREATED,
    ) -> tuple[bool, str]:
        """Apply the trust-level policy matrix to a scan result."""
        if trust == TrustLevel.BUILTIN:
            return True, ""
        policy = _INSTALL_POLICY.get(trust, _INSTALL_POLICY[TrustLevel.AGENT_CREATED])
        allowed = policy.get(result.verdict, False)
        if not allowed:
            messages = [f.message for f in result.findings if f.severity == "danger"]
            reason = "; ".join(messages[:3]) or f"Verdict '{result.verdict}' blocked for trust level '{trust.value}'"
            return False, reason
        if result.verdict == "caution" and trust == TrustLevel.AGENT_CREATED:
            warnings = [f.message for f in result.findings if f.severity == "warning"]
            if warnings:
                logger.warning(
                    "Agent-created skill has caution findings: {}",
                    "; ".join(warnings[:3]),
                )
        return True, ""

    def _check_structure(self, skill_dir: Path, result: ScanResult) -> None:
        files = list(skill_dir.rglob("*"))
        real_files = [f for f in files if f.is_file()]

        if len(real_files) > _MAX_FILES:
            result.findings.append(Finding(
                category="structural", severity="danger",
                message=f"Too many files ({len(real_files)} > {_MAX_FILES})",
            ))

        total_size = sum(f.stat().st_size for f in real_files)
        if total_size > _MAX_TOTAL_SIZE:
            result.findings.append(Finding(
                category="structural", severity="danger",
                message=f"Total size {total_size} exceeds {_MAX_TOTAL_SIZE} bytes",
            ))

        for f in real_files:
            if f.suffix.lower() in _BINARY_EXTENSIONS:
                result.findings.append(Finding(
                    category="structural", severity="danger",
                    message=f"Binary file detected: {f.name}",
                    file=str(f.relative_to(skill_dir)),
                ))

            if f.is_symlink():
                target = f.resolve()
                try:
                    target.relative_to(skill_dir.resolve())
                except ValueError:
                    result.findings.append(Finding(
                        category="structural", severity="danger",
                        message=f"Symlink escapes skill directory: {f.name} -> {target}",
                        file=str(f.relative_to(skill_dir)),
                    ))

            if f.stat().st_size > _MAX_SINGLE_FILE_SIZE:
                result.findings.append(Finding(
                    category="structural", severity="warning",
                    message=f"Large file: {f.name} ({f.stat().st_size} bytes)",
                    file=str(f.relative_to(skill_dir)),
                ))

    def _check_content(self, skill_dir: Path, result: ScanResult) -> None:
        for filepath in skill_dir.rglob("*"):
            if not filepath.is_file():
                continue
            if filepath.suffix.lower() in _BINARY_EXTENSIONS:
                continue

            try:
                content = filepath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            rel = str(filepath.relative_to(skill_dir))
            self._scan_text(content, rel, result)

    def _scan_text(self, content: str, rel_path: str, result: ScanResult) -> None:
        for line_num, line in enumerate(content.splitlines(), start=1):
            for pattern in _EXFIL_PATTERNS:
                if pattern.search(line):
                    result.findings.append(Finding(
                        category="exfiltration", severity="danger",
                        message=f"Potential data exfiltration: {line.strip()[:100]}",
                        file=rel_path, line=line_num,
                    ))

            for pattern in _INJECTION_PATTERNS:
                if pattern.search(line):
                    result.findings.append(Finding(
                        category="prompt_injection", severity="danger",
                        message=f"Prompt injection pattern: {line.strip()[:100]}",
                        file=rel_path, line=line_num,
                    ))

            for pattern in _DESTRUCTIVE_PATTERNS:
                if pattern.search(line):
                    result.findings.append(Finding(
                        category="destructive", severity="danger",
                        message=f"Destructive command: {line.strip()[:100]}",
                        file=rel_path, line=line_num,
                    ))

            for pattern in _PERSISTENCE_PATTERNS:
                if pattern.search(line):
                    result.findings.append(Finding(
                        category="persistence", severity="warning",
                        message=f"Persistence mechanism: {line.strip()[:100]}",
                        file=rel_path, line=line_num,
                    ))

            for pattern in _CREDENTIAL_PATTERNS:
                if pattern.search(line):
                    result.findings.append(Finding(
                        category="credentials", severity="danger",
                        message=f"Hardcoded credential: {line.strip()[:60]}...",
                        file=rel_path, line=line_num,
                    ))

        if _INVISIBLE_CHARS.search(content):
            result.findings.append(Finding(
                category="invisible_unicode", severity="warning",
                message="Invisible unicode characters detected",
                file=rel_path,
            ))
