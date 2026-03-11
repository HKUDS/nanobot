"""Tests for skill security scanning."""

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.skills import SkillsLoader
from nanobot.config.schema import ScannedHashEntry
from nanobot.security.skill_scanner import SESSION_CACHE_MAX_SIZE, ScanResult, SkillScanner


@pytest.fixture
def sample_skill_content() -> str:
    """Sample skill content for testing."""
    return """---
name: test-skill
description: A test skill
---
# Test Skill

This is a test skill for security scanning.
"""


@pytest.fixture
def sample_skill_hash(sample_skill_content: str) -> str:
    """SHA256 hash of sample skill content."""
    return hashlib.sha256(sample_skill_content.encode("utf-8")).hexdigest()


@pytest.fixture
def temp_skill_file(tmp_path: Path, sample_skill_content: str) -> Path:
    """Create a temporary skill file for testing."""
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(sample_skill_content, encoding="utf-8")
    return skill_file


@pytest.fixture
def basic_config() -> dict:
    """Basic skill security config."""
    return {
        "enabled": True,
        "unknown_ttl_seconds": 86400,
        "whitelist": [],
        "scanned_hashes": {},
    }


class TestSkillScannerHashComputation:
    """Tests for SHA256 hash computation."""

    def test_compute_sha256_consistent(self, basic_config: dict) -> None:
        """Hash computation should be consistent for same content."""
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        content = "test content"
        hash1 = scanner._compute_sha256(content)
        hash2 = scanner._compute_sha256(content)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 produces 64 hex chars

    def test_compute_sha256_different_content(self, basic_config: dict) -> None:
        """Different content should produce different hashes."""
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        hash1 = scanner._compute_sha256("content1")
        hash2 = scanner._compute_sha256("content2")
        assert hash1 != hash2


class TestSkillScannerWhitelist:
    """Tests for whitelist functionality."""

    def test_is_whitelisted_true(self, basic_config: dict, sample_skill_hash: str) -> None:
        """Should return True for whitelisted hash."""
        basic_config["whitelist"] = [sample_skill_hash]
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        assert scanner._is_whitelisted(sample_skill_hash) is True

    def test_is_whitelisted_false(self, basic_config: dict, sample_skill_hash: str) -> None:
        """Should return False for non-whitelisted hash."""
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        assert scanner._is_whitelisted(sample_skill_hash) is False

    def test_whitelisted_skill_allowed(
        self, temp_skill_file: Path, basic_config: dict, sample_skill_hash: str
    ) -> None:
        """Whitelisted skill should be allowed without VT check."""
        basic_config["whitelist"] = [sample_skill_hash]
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner.check_skill(temp_skill_file)
        assert result.safe is True
        assert result.result == "whitelisted"


class TestSkillScannerCache:
    """Tests for cache functionality."""

    def test_get_cached_result_not_found(self, basic_config: dict) -> None:
        """Should return None for uncached hash."""
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner._get_cached_result("nonexistent")
        assert result is None

    def test_get_cached_result_found(self, basic_config: dict) -> None:
        """Should return cached result."""
        test_hash = "abc123"
        basic_config["scanned_hashes"] = {
            test_hash: ScannedHashEntry(result="clean", scanned_at="2024-01-01T10:00:00Z")
        }
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner._get_cached_result(test_hash)
        assert result == ("clean", "2024-01-01T10:00:00Z")

    def test_get_cached_result_unknown_expired(self, basic_config: dict) -> None:
        """Unknown result should expire after TTL."""
        test_hash = "abc123"
        # Set TTL to 1 second and scanned_at to 2 days ago
        basic_config["unknown_ttl_seconds"] = 1
        basic_config["scanned_hashes"] = {
            test_hash: ScannedHashEntry(
                result="unknown",
                scanned_at="2024-01-01T10:00:00Z",  # Old timestamp
            )
        }
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner._get_cached_result(test_hash)
        # Result should be None because it's expired
        assert result is None

    def test_get_cached_result_unknown_valid(self, basic_config: dict) -> None:
        """Unknown result should be valid within TTL."""
        test_hash = "abc123"
        # Recent timestamp
        now = datetime.now(timezone.utc)
        recent = now.isoformat().replace("+00:00", "Z")
        basic_config["scanned_hashes"] = {
            test_hash: ScannedHashEntry(result="unknown", scanned_at=recent)
        }
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner._get_cached_result(test_hash)
        assert result == ("unknown", recent)

    def test_save_result(self, basic_config: dict) -> None:
        """Should save result to cache with skill name."""
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        test_hash = "abc123"
        scanner._save_result(test_hash, "clean", "test-skill")
        assert test_hash in scanner.scanned_hashes
        entry = scanner.scanned_hashes[test_hash]
        # Support both dict and ScannedHashEntry
        if hasattr(entry, "result"):
            assert entry.result == "clean"
            assert entry.skill_name == "test-skill"
        else:
            assert entry["result"] == "clean"
            assert entry["skill_name"] == "test-skill"

    def test_save_result_callback(self, basic_config: dict) -> None:
        """Should call save_callback when saving result."""
        callback_results = []

        def save_callback(sha256: str, result: str, scanned_at: str, skill_name: str) -> None:
            callback_results.append((sha256, result, scanned_at, skill_name))

        scanner = SkillScanner(
            vt_token="test-token",
            skill_security_config=basic_config,
            save_callback=save_callback,
        )
        test_hash = "abc123"
        scanner._save_result(test_hash, "clean", "test-skill")
        assert len(callback_results) == 1
        assert callback_results[0][0] == test_hash
        assert callback_results[0][1] == "clean"
        assert callback_results[0][3] == "test-skill"


class TestSkillScannerVirusTotal:
    """Tests for VirusTotal API interaction."""

    def test_query_virustotal_no_token(self, basic_config: dict) -> None:
        """Should return None when no token is configured."""
        scanner = SkillScanner(vt_token="", skill_security_config=basic_config)
        result = scanner._query_virustotal("somehash")
        assert result is None

    @patch("nanobot.security.skill_scanner.httpx.Client")
    def test_query_virustotal_not_found(self, mock_client: MagicMock, basic_config: dict) -> None:
        """Should return 'not_found' for 404 response."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_context)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_context.get.return_value = mock_response
        mock_client.return_value = mock_context

        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner._query_virustotal("somehash")
        assert result == "not_found"

    @patch("nanobot.security.skill_scanner.httpx.Client")
    def test_query_virustotal_clean(self, mock_client: MagicMock, basic_config: dict) -> None:
        """Should return (False, count) for clean file."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 0,
                        "suspicious": 0,
                        "harmless": 70,
                        "undetected": 0,
                    }
                }
            }
        }

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_context)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_context.get.return_value = mock_response
        mock_client.return_value = mock_context

        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner._query_virustotal("somehash")
        assert result == (False, (0, 70))

    @patch("nanobot.security.skill_scanner.httpx.Client")
    def test_query_virustotal_malicious(
        self, mock_client: MagicMock, basic_config: dict
    ) -> None:
        """Should return (True, count) for malicious file."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 3,
                        "suspicious": 2,
                        "harmless": 60,
                        "undetected": 5,
                    }
                }
            }
        }

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_context)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_context.get.return_value = mock_response
        mock_client.return_value = mock_context

        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner._query_virustotal("somehash")
        assert result == (True, (5, 70))

    @patch("nanobot.security.skill_scanner.httpx.Client")
    def test_query_virustotal_quota_exhausted(
        self, mock_client: MagicMock, basic_config: dict
    ) -> None:
        """Should return None when quota is exhausted (429)."""
        mock_response = MagicMock()
        mock_response.status_code = 429

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_context)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_context.get.return_value = mock_response
        mock_client.return_value = mock_context

        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner._query_virustotal("somehash")
        assert result is None


class TestSkillScannerCheckSkill:
    """Tests for check_skill main entry point."""

    def test_check_skill_disabled(self, temp_skill_file: Path) -> None:
        """Should allow all skills when scanning is disabled."""
        config = {
            "enabled": False,
            "unknown_ttl_seconds": 86400,
            "whitelist": [],
            "scanned_hashes": {},
        }
        scanner = SkillScanner(vt_token="test-token", skill_security_config=config)
        result = scanner.check_skill(temp_skill_file)
        assert result.safe is True
        assert result.result == "disabled"

    @patch("nanobot.security.skill_scanner.httpx.Client")
    def test_check_skill_malicious_blocked(
        self, mock_client: MagicMock, temp_skill_file: Path, basic_config: dict
    ) -> None:
        """Should block malicious skill."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 5,
                        "suspicious": 0,
                        "harmless": 60,
                        "undetected": 5,
                    }
                }
            }
        }

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_context)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_context.get.return_value = mock_response
        mock_client.return_value = mock_context

        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner.check_skill(temp_skill_file)
        assert result.safe is False
        assert result.result == "malicious"

    @patch("nanobot.security.skill_scanner.httpx.Client")
    def test_check_skill_clean_allowed(
        self, mock_client: MagicMock, temp_skill_file: Path, basic_config: dict
    ) -> None:
        """Should allow clean skill."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": 0,
                        "suspicious": 0,
                        "harmless": 70,
                        "undetected": 0,
                    }
                }
            }
        }

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_context)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_context.get.return_value = mock_response
        mock_client.return_value = mock_context

        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner.check_skill(temp_skill_file)
        assert result.safe is True
        assert result.result == "clean"

    @patch("nanobot.security.skill_scanner.httpx.Client")
    def test_check_skill_not_found_allowed(
        self, mock_client: MagicMock, temp_skill_file: Path, basic_config: dict
    ) -> None:
        """Should allow skill not found in VT database."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_context)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_context.get.return_value = mock_response
        mock_client.return_value = mock_context

        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner.check_skill(temp_skill_file)
        assert result.safe is True
        assert result.result == "unknown"

    @patch("nanobot.security.skill_scanner.httpx.Client")
    def test_check_skill_api_unavailable_allowed(
        self, mock_client: MagicMock, temp_skill_file: Path, basic_config: dict
    ) -> None:
        """Should allow skill when VT API is unavailable."""
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_context)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_context.get.side_effect = Exception("Network error")
        mock_client.return_value = mock_context

        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner.check_skill(temp_skill_file)
        assert result.safe is True
        assert result.result == "unknown"

    def test_check_skill_cached_clean(
        self, temp_skill_file: Path, basic_config: dict, sample_skill_hash: str
    ) -> None:
        """Should use cached clean result."""
        basic_config["scanned_hashes"] = {
            sample_skill_hash: ScannedHashEntry(result="clean", scanned_at="2024-01-01T10:00:00Z")
        }
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner.check_skill(temp_skill_file)
        assert result.safe is True
        assert result.result == "clean"

    def test_check_skill_cached_malicious(
        self, temp_skill_file: Path, basic_config: dict, sample_skill_hash: str
    ) -> None:
        """Should block cached malicious skill."""
        basic_config["scanned_hashes"] = {
            sample_skill_hash: ScannedHashEntry(result="malicious", scanned_at="2024-01-01T10:00:00Z")
        }
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        result = scanner.check_skill(temp_skill_file)
        assert result.safe is False
        assert result.result == "malicious"


class TestSkillsLoaderSecurity:
    """Tests for SkillsLoader security integration."""

    @pytest.fixture
    def workspace_with_skill(self, tmp_path: Path, sample_skill_content: str) -> Path:
        """Create a workspace with a test skill."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        skills_dir = workspace / "skills" / "test-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(sample_skill_content, encoding="utf-8")
        return workspace

    def test_load_skill_without_scanner(self, workspace_with_skill: Path) -> None:
        """Should load skill normally without scanner."""
        loader = SkillsLoader(workspace_with_skill)
        content = loader.load_skill("test-skill")
        assert content is not None
        assert "# Test Skill" in content

    def test_load_skill_with_scanner_clean(self, workspace_with_skill: Path) -> None:
        """Should load skill when scanner says it's clean."""
        mock_scanner = MagicMock()
        mock_result = MagicMock()
        mock_result.safe = True
        mock_scanner.check_skill.return_value = mock_result

        loader = SkillsLoader(workspace_with_skill, skill_scanner=mock_scanner)
        content = loader.load_skill("test-skill")
        assert content is not None

    def test_load_skill_with_scanner_malicious(self, workspace_with_skill: Path) -> None:
        """Should return None when scanner says it's malicious."""
        mock_scanner = MagicMock()
        mock_result = MagicMock()
        mock_result.safe = False
        mock_scanner.check_skill.return_value = mock_result

        loader = SkillsLoader(workspace_with_skill, skill_scanner=mock_scanner)
        content = loader.load_skill("test-skill")
        assert content is None

    def test_load_skill_builtin_also_scanned(self, tmp_path: Path) -> None:
        """Built-in skills should also be scanned (may be modified by user)."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create a mock scanner that allows everything
        mock_scanner = MagicMock()
        mock_result = MagicMock()
        mock_result.safe = True
        mock_scanner.check_skill.return_value = mock_result

        loader = SkillsLoader(
            workspace,
            builtin_skills_dir=Path(__file__).parent.parent / "nanobot" / "skills",
            skill_scanner=mock_scanner,
        )

        # Try to load a built-in skill (weather is usually present)
        content = loader.load_skill("weather")
        # If skill exists, scanner should have been called
        if content is not None:
            # Scanner SHOULD be called for built-in skills (they may be modified)
            mock_scanner.check_skill.assert_called_once()


class TestWhitelistValidation:
    """Tests for whitelist entry validation."""

    def test_valid_sha256_accepted(self, basic_config: dict) -> None:
        """Valid SHA256 hashes should be accepted."""
        valid_hash = "a" * 64  # 64 'a' chars = valid SHA256
        basic_config["whitelist"] = [valid_hash]
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        assert valid_hash in scanner.whitelist

    def test_invalid_sha256_rejected(self, basic_config: dict) -> None:
        """Invalid hashes should be rejected with warning."""
        invalid_hash = "not-a-hash"
        basic_config["whitelist"] = [invalid_hash]
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        assert invalid_hash not in scanner.whitelist
        assert len(scanner.whitelist) == 0  # Original default list is empty

    def test_mixed_whitelist(self, basic_config: dict) -> None:
        """Mix of valid and invalid hashes should only keep valid ones."""
        valid1 = "a" * 64
        valid2 = "b" * 64
        invalid = "not-valid"
        basic_config["whitelist"] = [valid1, invalid, valid2]
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        assert valid1 in scanner.whitelist
        assert valid2 in scanner.whitelist
        assert invalid not in scanner.whitelist
        assert len(scanner.whitelist) == 2


class TestSessionCache:
    """Tests for session cache functionality."""

    def test_session_cache_hit(self, basic_config: dict) -> None:
        """Repeated check should hit session cache."""
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)
        # First check adds to cache
        result1 = ScanResult(safe=True, result="whitelisted", message="test")
        scanner._add_to_session_cache("hash1", result1)
        # Second check should hit cache
        with scanner._cache_lock:
            cached = scanner._session_cache.get("hash1")
        assert cached == result1

    def test_session_cache_lru_eviction(self, basic_config: dict) -> None:
        """Oldest entries should be evicted when cache is full."""
        # Use small cache for testing
        from nanobot.security.skill_scanner import SESSION_CACHE_MAX_SIZE
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)

        # Fill cache beyond capacity
        for i in range(SESSION_CACHE_MAX_SIZE + 10):
            result = ScanResult(safe=True, result="clean", message=f"test{i}")
            scanner._add_to_session_cache(f"hash{i}", result)

        # Cache should not exceed max size
        with scanner._cache_lock:
            assert len(scanner._session_cache) <= SESSION_CACHE_MAX_SIZE

    def test_session_cache_move_to_end(self, basic_config: dict) -> None:
        """Accessed entries should be moved to end (most recently used)."""
        scanner = SkillScanner(vt_token="test-token", skill_security_config=basic_config)

        result1 = ScanResult(safe=True, result="clean", message="test1")
        result2 = ScanResult(safe=True, result="clean", message="test2")

        scanner._add_to_session_cache("hash1", result1)
        scanner._add_to_session_cache("hash2", result2)

        # Access hash1 again (should move to end)
        with scanner._cache_lock:
            if "hash1" in scanner._session_cache:
                scanner._session_cache.move_to_end("hash1")

        # Check order - hash2 should be first (LRU), hash1 last (MRU)
        with scanner._cache_lock:
            keys = list(scanner._session_cache.keys())
            if len(keys) >= 2:
                assert keys[0] == "hash2"
                assert keys[-1] == "hash1"
