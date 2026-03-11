"""VirusTotal-based security scanning for skills."""

import hashlib
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

import httpx
from loguru import logger

from nanobot.config.schema import ScannedHashEntry

# VirusTotal API endpoint for file reports
VT_API_URL = "https://www.virustotal.com/api/v3/files/{hash}"

# Named constants
SHA256_DISPLAY_LENGTH = 16  # Truncate hash for display
SESSION_CACHE_MAX_SIZE = 256  # Maximum entries in session cache

# Valid SHA256 hash pattern
SHA256_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")


@dataclass
class ScanResult:
    """Result of a skill security scan."""

    safe: bool  # True if the skill is safe to load
    result: Literal["clean", "malicious", "unknown", "whitelisted", "cached", "disabled", "error"]
    message: str  # Human-readable message


class SkillScanner:
    """
    Scans skill files using VirusTotal for malware detection.

    Scan flow:
    1. Check in-memory session cache (prevents redundant checks within same request)
    2. Check whitelist - if found, allow
    3. Check persistent cache - if found and valid, use cached result
    4. Query VirusTotal API
    5. Cache result and make decision

    Thread-safe: Uses locks to protect session cache and persistent cache access.
    """

    def __init__(
        self,
        vt_token: str,
        skill_security_config: dict,
        save_callback: Callable[[str, str, str, str], None] | None = None,
    ):
        """
        Initialize the skill scanner.

        Args:
            vt_token: VirusTotal API token.
            skill_security_config: Configuration dict with keys:
                - enabled: bool
                - unknown_ttl_seconds: int
                - whitelist: list[str]
                - scanned_hashes: dict
            save_callback: Optional callback to save scan results.
                Called as save_callback(sha256, result, scanned_at, skill_name).
        """
        self.vt_token = vt_token
        self.enabled = skill_security_config.get("enabled", True)
        self.unknown_ttl_seconds = skill_security_config.get("unknown_ttl_seconds", 86400)
        self.scanned_hashes = skill_security_config.get("scanned_hashes", {})
        self.save_callback = save_callback

        # Validate and filter whitelist entries
        raw_whitelist = skill_security_config.get("whitelist", [])
        self.whitelist = self._validate_whitelist(raw_whitelist)

        # Thread-safe LRU session cache
        self._session_cache: OrderedDict[str, ScanResult] = OrderedDict()
        self._cache_lock = threading.Lock()

    def _validate_whitelist(self, raw_whitelist: list[str]) -> set[str]:
        """Validate whitelist entries as valid SHA256 hashes."""
        valid = set()
        for entry in raw_whitelist:
            if SHA256_PATTERN.match(entry):
                valid.add(entry.lower())
            else:
                logger.warning(f"Invalid SHA256 hash in whitelist, ignoring: {entry[:16]}...")
        return valid

    def check_skill(self, skill_path: Path) -> ScanResult:
        """
        Check if a skill file is safe to load.

        Args:
            skill_path: Path to the skill file (SKILL.md).

        Returns:
            ScanResult with safety decision and details.
        """
        skill_name = skill_path.parent.name

        # If security scanning is disabled, allow all
        if not self.enabled:
            return ScanResult(safe=True, result="disabled", message="Security scanning disabled")

        # Compute SHA256 hash
        try:
            content = skill_path.read_text(encoding="utf-8")
            sha256 = self._compute_sha256(content)
        except Exception as e:
            logger.warning(f"Failed to compute hash for skill '{skill_name}': {e}")
            return ScanResult(safe=True, result="error", message=f"Hash computation failed: {e}")

        # Check in-memory session cache first (thread-safe with LRU eviction)
        with self._cache_lock:
            if sha256 in self._session_cache:
                # Move to end (most recently used)
                self._session_cache.move_to_end(sha256)
                return self._session_cache[sha256]

        # Check whitelist
        if self._is_whitelisted(sha256):
            logger.debug(f"Skill '{skill_name}' in whitelist, skipping scan")
            result = ScanResult(safe=True, result="whitelisted", message="Skill is whitelisted")
            self._add_to_session_cache(sha256, result)
            return result

        # Check persistent cache
        cached = self._get_cached_result(sha256)
        if cached:
            cache_result, scanned_at = cached
            if cache_result == "malicious":
                logger.warning(f"Skill '{skill_name}' blocked: cached as malicious")
                result = ScanResult(safe=False, result="malicious", message="Cached as malicious")
                self._add_to_session_cache(sha256, result)
                return result
            elif cache_result == "clean":
                result = ScanResult(safe=True, result="clean", message="Cached as clean")
                self._add_to_session_cache(sha256, result)
                return result
            # For "unknown", continue to re-scan (TTL already handled in _get_cached_result)

        # Query VirusTotal
        logger.debug(f"Skill '{skill_name}' has hash {sha256[:SHA256_DISPLAY_LENGTH]}..., querying VT...")
        vt_result = self._query_virustotal(sha256)

        if vt_result is None:
            # API unavailable or error
            logger.warning(f"VirusTotal API unavailable, allowing skill '{skill_name}'")
            self._save_result(sha256, "unknown", skill_name)
            result = ScanResult(
                safe=True,
                result="unknown",
                message="VirusTotal API unavailable, allowed with caution"
            )
            self._add_to_session_cache(sha256, result)
            return result

        if vt_result == "not_found":
            # Hash not in VT database
            logger.info(f"Skill '{skill_name}' not in VT database, allowing with caution")
            self._save_result(sha256, "unknown", skill_name)
            result = ScanResult(
                safe=True,
                result="unknown",
                message="Hash not found in VirusTotal database"
            )
            self._add_to_session_cache(sha256, result)
            return result

        # We have a result from VT
        is_malicious, engine_count = vt_result
        self._save_result(sha256, "malicious" if is_malicious else "clean", skill_name)

        if is_malicious:
            logger.warning(
                f"Skill '{skill_name}' blocked: {engine_count[0]}/{engine_count[1]} "
                "engines detected malicious"
            )
            result = ScanResult(
                safe=False,
                result="malicious",
                message=f"{engine_count[0]}/{engine_count[1]} engines detected malicious"
            )
        else:
            logger.debug(f"Skill '{skill_name}' passed security scan")
            result = ScanResult(safe=True, result="clean", message="No malicious content detected")

        self._add_to_session_cache(sha256, result)
        return result

    def _add_to_session_cache(self, sha256: str, result: ScanResult) -> None:
        """Add result to session cache with LRU eviction (thread-safe)."""
        with self._cache_lock:
            # Evict oldest if at capacity
            while len(self._session_cache) >= SESSION_CACHE_MAX_SIZE:
                self._session_cache.popitem(last=False)
            self._session_cache[sha256] = result
            # Move to end (most recently used)
            self._session_cache.move_to_end(sha256)

    def _compute_sha256(self, content: str) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _query_virustotal(self, sha256: str) -> tuple[bool, tuple[int, int]] | str | None:
        """
        Query VirusTotal API for a file hash.

        Args:
            sha256: SHA256 hash to query.

        Returns:
            - (is_malicious, (malicious_count, total_count)) if found
            - "not_found" if hash not in database
            - None if API unavailable or error
        """
        if not self.vt_token:
            logger.debug("No VirusTotal token configured")
            return None

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    VT_API_URL.format(hash=sha256),
                    headers={"x-apikey": self.vt_token}
                )

                if response.status_code == 404:
                    return "not_found"

                if response.status_code == 429:
                    logger.warning("VirusTotal API quota exhausted")
                    return None

                response.raise_for_status()

                data = response.json()
                attributes = data.get("data", {}).get("attributes", {})
                last_analysis_stats = attributes.get("last_analysis_stats", {})

                malicious = last_analysis_stats.get("malicious", 0)
                suspicious = last_analysis_stats.get("suspicious", 0)
                harmless = last_analysis_stats.get("harmless", 0)
                undetected = last_analysis_stats.get("undetected", 0)

                total = malicious + suspicious + harmless + undetected
                is_malicious = malicious > 0 or suspicious > 0

                return (is_malicious, (malicious + suspicious, total))

        except httpx.TimeoutException:
            logger.warning("VirusTotal API timeout")
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(f"VirusTotal API error: {e}")
            return None
        except Exception as e:
            logger.warning(f"VirusTotal API request failed: {e}")
            return None

    def _is_whitelisted(self, sha256: str) -> bool:
        """Check if a hash is in the whitelist."""
        return sha256 in self.whitelist

    def _get_cached_result(self, sha256: str) -> tuple[str, str] | None:
        """
        Get cached scan result for a hash (thread-safe).

        Returns:
            (result, scanned_at) tuple or None if not cached or expired.
        """
        with self._cache_lock:
            entry = self.scanned_hashes.get(sha256)
            if not entry:
                return None

            # ScannedHashEntry is a Pydantic model
            result = entry.result
            scanned_at = entry.scanned_at

        # For "unknown" results, check TTL
        if result == "unknown" and scanned_at:
            try:
                scanned_time = datetime.fromisoformat(scanned_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                age_seconds = (now - scanned_time).total_seconds()

                if age_seconds > self.unknown_ttl_seconds:
                    logger.debug(
                        f"Cached 'unknown' result expired (age: {int(age_seconds)}s > "
                        f"TTL: {self.unknown_ttl_seconds}s), re-scanning"
                    )
                    return None
            except (ValueError, TypeError):
                pass  # Invalid timestamp, treat as not cached

        return (result, scanned_at)

    def _save_result(self, sha256: str, result: str, skill_name: str) -> None:
        """
        Save a scan result to cache (thread-safe).

        Args:
            sha256: The file hash.
            result: The scan result ("clean", "malicious", "unknown").
            skill_name: The name of the skill for easier identification.
        """
        scanned_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Create entry (ScannedHashEntry is a Pydantic model)
        entry = ScannedHashEntry(
            result=result,
            scanned_at=scanned_at,
            skill_name=skill_name,
        )

        # Update local cache with lock
        with self._cache_lock:
            self.scanned_hashes[sha256] = entry

        # Call save callback if provided
        if self.save_callback:
            try:
                self.save_callback(sha256, result, scanned_at, skill_name)
            except Exception as e:
                logger.warning(f"Failed to save scan result: {e}")

    def preload_skills(self, skill_paths: list[Path]) -> dict[str, ScanResult]:
        """
        Pre-scan all skills at startup to populate cache.

        Args:
            skill_paths: List of skill file paths to scan.

        Returns:
            Dict mapping skill names to their scan results.
        """
        if not self.enabled:
            logger.info("Security scanning disabled, skipping preload")
            return {}

        logger.info(f"Pre-scanning {len(skill_paths)} skills for security...")
        start_time = datetime.now()

        results = {}
        for path in skill_paths:
            if path.exists():
                skill_name = path.parent.name
                results[skill_name] = self.check_skill(path)

        elapsed = (datetime.now() - start_time).total_seconds()
        safe_count = sum(1 for r in results.values() if r.safe)
        blocked_count = len(results) - safe_count
        logger.info(
            f"Skill pre-scan complete: {safe_count} safe, {blocked_count} blocked ({elapsed:.1f}s)"
        )

        return results
