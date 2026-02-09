"""Tests for calibration system."""

import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from nanobot.agent.router.calibration import CalibrationManager
from nanobot.agent.router.models import RoutingPattern, RoutingTier


class TestCalibrationManager:
    """Test CalibrationManager."""
    
    def test_init(self, tmp_path):
        """Test initialization."""
        patterns_file = tmp_path / "patterns.json"
        analytics_file = tmp_path / "analytics.json"
        
        config = {
            "interval": "24h",
            "min_classifications": 50,
            "max_patterns": 100,
        }
        
        manager = CalibrationManager(
            patterns_file=patterns_file,
            analytics_file=analytics_file,
            config=config,
        )
        
        assert manager.patterns_file == patterns_file
        assert manager.analytics_file == analytics_file
        assert manager.interval == "24h"
        assert manager.min_classifications == 50
        assert manager.max_patterns == 100
    
    def test_record_classification(self):
        """Test recording classifications."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        record = {
            "content_preview": "Test message",
            "final_tier": "simple",
            "final_confidence": 0.9,
            "layer": "client",
        }
        
        manager.record_classification(record)
        
        assert len(manager._classifications) == 1
        assert manager._classifications[0]["content_preview"] == "Test message"
        assert "timestamp" in manager._classifications[0]
    
    def test_record_classification_limits_size(self):
        """Test that old classifications are removed after 1000."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        # Add 1001 classifications
        for i in range(1001):
            manager.record_classification({"id": i})
        
        # Should only keep last 1000
        assert len(manager._classifications) == 1000
        # First one should be removed
        assert manager._classifications[0]["id"] == 1
    
    def test_should_calibrate_no_data(self):
        """Test calibration check with no data."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={"min_classifications": 50},
        )
        
        assert manager.should_calibrate() is False
    
    def test_should_calibrate_enough_data(self):
        """Test calibration check with enough data."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={"interval": "24h", "min_classifications": 50},
        )
        
        # Add 50+ classifications
        for i in range(60):
            manager.record_classification({"id": i})
        
        # No last calibration, so should calibrate
        assert manager.should_calibrate() is True
    
    def test_should_calibrate_recent_calibration(self):
        """Test calibration check when recently calibrated."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={"interval": "24h", "min_classifications": 50},
        )
        
        # Set recent calibration
        manager._last_calibration = datetime.now()
        
        # Add some classifications
        for i in range(60):
            manager.record_classification({"id": i})
        
        # Should not calibrate again immediately
        assert manager.should_calibrate() is False
    
    def test_should_calibrate_count_override(self):
        """Test calibration when count threshold overrides time."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={"interval": "24h", "min_classifications": 50},
        )
        
        # Set recent calibration
        manager._last_calibration = datetime.now()
        
        # Add many classifications (overrides time threshold)
        for i in range(100):
            manager.record_classification({"id": i})
        
        # Should calibrate due to count
        assert manager.should_calibrate() is True
    
    def test_analyze_accuracy(self):
        """Test accuracy analysis."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        # Add classifications with matches and mismatches
        manager._classifications = [
            {"client_tier": "simple", "llm_tier": "simple"},  # Match
            {"client_tier": "complex", "llm_tier": "complex"},  # Match
            {"client_tier": "simple", "llm_tier": "medium"},  # Mismatch
        ]
        
        report = manager._analyze_accuracy()
        
        assert report["total"] == 3
        assert report["matches"] == 2
        assert report["accuracy"] == pytest.approx(2/3)
        assert len(report["mismatches"]) == 1
    
    def test_analyze_accuracy_no_llm_data(self):
        """Test accuracy analysis when no LLM comparisons."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        manager._classifications = [
            {"final_tier": "simple"},  # No LLM data
        ]
        
        report = manager._analyze_accuracy()
        
        assert report["total"] == 1
        assert report["matches"] == 0  # Can't match without LLM data
    
    def test_extract_patterns(self):
        """Test pattern extraction from content samples."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        contents = [
            "Debug this code error",
            "Debug the issue",
            "Debug system failure",
        ]
        
        patterns = manager._extract_patterns(contents)
        
        assert len(patterns) > 0
        assert any("debug" in p.lower() for p in patterns)
    
    def test_extract_patterns_no_common_words(self):
        """Test pattern extraction with no common meaningful words."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        contents = [
            "abc xyz 123",
            "def uvw 456",
        ]
        
        patterns = manager._extract_patterns(contents)
        
        # Should not find patterns (all words < 4 chars)
        assert len(patterns) == 0
    
    def test_evict_patterns(self):
        """Test pattern eviction based on success rate."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        patterns = [
            RoutingPattern(
                regex=r"test1",
                tier=RoutingTier.SIMPLE,
                confidence=0.8,
                examples=[],
                added_at=datetime.now().isoformat(),
                success_rate=0.5,  # Good
            ),
            RoutingPattern(
                regex=r"test2",
                tier=RoutingTier.MEDIUM,
                confidence=0.8,
                examples=[],
                added_at=datetime.now().isoformat(),
                success_rate=0.1,  # Bad but recent
            ),
            RoutingPattern(
                regex=r"test3",
                tier=RoutingTier.COMPLEX,
                confidence=0.8,
                examples=[],
                added_at=(datetime.now() - timedelta(days=10)).isoformat(),
                success_rate=0.1,  # Bad and old
            ),
        ]
        
        result = manager._evict_patterns(patterns)
        
        # Should keep first two, evict third
        assert len(result) == 2
        assert result[0].regex == r"test1"
        assert result[1].regex == r"test2"
    
    def test_parse_interval_hours(self):
        """Test interval parsing for hours."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        assert manager._parse_interval("24h") == 24
        assert manager._parse_interval("48h") == 48
    
    def test_parse_interval_days(self):
        """Test interval parsing for days."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        assert manager._parse_interval("1d") == 24
        assert manager._parse_interval("7d") == 168
    
    def test_parse_interval_numeric(self):
        """Test interval parsing for plain numbers."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        assert manager._parse_interval("100") == 100
    
    def test_parse_interval_default(self):
        """Test interval parsing with invalid format."""
        manager = CalibrationManager(
            patterns_file=Path("/tmp/test_patterns.json"),
            config={},
        )
        
        assert manager._parse_interval("invalid") == 24  # Default


class TestCalibrationFileOperations:
    """Test file operations in calibration."""
    
    def test_load_existing_patterns(self, tmp_path):
        """Test loading existing patterns from file."""
        patterns_file = tmp_path / "patterns.json"
        
        # Create file with patterns
        data = {
            "patterns": [
                {
                    "regex": r"test",
                    "tier": "simple",
                    "confidence": 0.8,
                    "examples": [],
                    "added_at": datetime.now().isoformat(),
                }
            ]
        }
        patterns_file.write_text(json.dumps(data))
        
        manager = CalibrationManager(
            patterns_file=patterns_file,
            config={},
        )
        
        patterns = manager._load_existing_patterns()
        assert len(patterns) == 1
        assert patterns[0].regex == r"test"
    
    def test_save_patterns(self, tmp_path):
        """Test saving patterns to file."""
        patterns_file = tmp_path / "patterns.json"
        
        manager = CalibrationManager(
            patterns_file=patterns_file,
            config={},
        )
        
        patterns = [
            RoutingPattern(
                regex=r"test",
                tier=RoutingTier.SIMPLE,
                confidence=0.8,
                examples=["example"],
                added_at=datetime.now().isoformat(),
            )
        ]
        
        manager._save_patterns(patterns)
        
        # Verify file was created
        assert patterns_file.exists()
        data = json.loads(patterns_file.read_text())
        assert len(data["patterns"]) == 1
        assert data["version"] == "1.0"
    
    def test_backup_patterns(self, tmp_path):
        """Test pattern backup before calibration."""
        patterns_file = tmp_path / "patterns.json"
        patterns_file.write_text(json.dumps({"patterns": []}))
        
        manager = CalibrationManager(
            patterns_file=patterns_file,
            config={"backup_before_calibration": True},
        )
        
        manager._backup_patterns()
        
        backup_file = tmp_path / "patterns.backup.json"
        assert backup_file.exists()
    
    def test_load_analytics(self, tmp_path):
        """Test loading analytics from file."""
        analytics_file = tmp_path / "analytics.json"
        
        data = {
            "classifications": [{"id": 1}],
            "last_calibration": datetime.now().isoformat(),
        }
        analytics_file.write_text(json.dumps(data))
        
        manager = CalibrationManager(
            patterns_file=tmp_path / "patterns.json",
            analytics_file=analytics_file,
            config={},
        )
        
        manager._load_analytics()
        
        assert len(manager._classifications) == 1
        assert manager._last_calibration is not None
    
    def test_save_analytics(self, tmp_path):
        """Test saving analytics to file."""
        analytics_file = tmp_path / "analytics.json"
        
        manager = CalibrationManager(
            patterns_file=tmp_path / "patterns.json",
            analytics_file=analytics_file,
            config={},
        )
        
        manager._classifications = [{"id": 1}]
        manager._last_calibration = datetime.now()
        
        manager._save_analytics()
        
        assert analytics_file.exists()
        data = json.loads(analytics_file.read_text())
        assert len(data["classifications"]) == 1
