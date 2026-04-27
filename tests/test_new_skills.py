"""Tests for new skills: stock-analysis, code-performance, and test-generator."""

import pytest
from pathlib import Path
from nanobot.agent.skills import SkillsLoader


class TestNewSkills:
    """Test suite for newly added skills."""
    
    @pytest.fixture
    def skills_loader(self, tmp_path):
        """Create a skills loader instance."""
        builtin_skills = Path(__file__).parent.parent / "nanobot" / "skills"
        return SkillsLoader(workspace=tmp_path, builtin_skills_dir=builtin_skills)
    
    def test_stock_analysis_skill_exists(self, skills_loader):
        """Test that stock-analysis skill can be loaded."""
        skill_content = skills_loader.load_skill("stock-analysis")
        assert skill_content is not None
        assert "Stock Market Analysis" in skill_content
        assert "Yahoo Finance" in skill_content
    
    def test_code_performance_skill_exists(self, skills_loader):
        """Test that code-performance skill can be loaded."""
        skill_content = skills_loader.load_skill("code-performance")
        assert skill_content is not None
        assert "Code Performance Analysis" in skill_content
        assert "cProfile" in skill_content
    
    def test_test_generator_skill_exists(self, skills_loader):
        """Test that test-generator skill can be loaded."""
        skill_content = skills_loader.load_skill("test-generator")
        assert skill_content is not None
        assert "Test Case Generator" in skill_content
        assert "pytest" in skill_content
    
    def test_all_new_skills_listed(self, skills_loader):
        """Test that all new skills appear in the skills list."""
        skills = skills_loader.list_skills(filter_unavailable=False)
        skill_names = [s["name"] for s in skills]
        
        assert "stock-analysis" in skill_names
        assert "code-performance" in skill_names
        assert "test-generator" in skill_names
    
    def test_new_skills_metadata(self, skills_loader):
        """Test that new skills have proper metadata."""
        # Stock analysis metadata
        stock_meta = skills_loader.get_skill_metadata("stock-analysis")
        assert stock_meta is not None
        assert stock_meta["name"] == "stock-analysis"
        assert "market data" in stock_meta["description"].lower() or "stock" in stock_meta["description"].lower()
        
        # Code performance metadata
        perf_meta = skills_loader.get_skill_metadata("code-performance")
        assert perf_meta is not None
        assert perf_meta["name"] == "code-performance"
        assert "performance" in perf_meta["description"].lower() or "profile" in perf_meta["description"].lower()
        
        # Test generator metadata
        test_meta = skills_loader.get_skill_metadata("test-generator")
        assert test_meta is not None
        assert test_meta["name"] == "test-generator"
        assert "test" in test_meta["description"].lower()
    
    def test_skills_summary_includes_new_skills(self, skills_loader):
        """Test that skills summary includes all new skills."""
        summary = skills_loader.build_skills_summary()
        
        assert "stock-analysis" in summary
        assert "code-performance" in summary
        assert "test-generator" in summary
        assert "<skills>" in summary
        assert "</skills>" in summary
    
    def test_stock_analysis_content_structure(self, skills_loader):
        """Test that stock-analysis skill has expected sections."""
        content = skills_loader.load_skill("stock-analysis")
        
        # Check for key sections
        assert "Quick Stock Quote" in content or "stock quote" in content.lower()
        assert "Historical Data" in content or "historical" in content.lower()
        assert "Technical Indicators" in content or "indicators" in content.lower()
        # Check for data engineering mention
        assert "Data Engineering" in content or "data engineering" in content.lower()
        # Check for new exchange support
        assert "NYSE" in content or "New York Stock Exchange" in content
        assert "DSE" in content or "Dhaka" in content
        assert "CSE" in content or "Colombo" in content
        # Check for FX/Forex support
        assert "FX" in content or "Forex" in content or "forex" in content.lower()
        # Check for AI trading suggestions
        assert "AI" in content or "trading" in content.lower()
        # Check for financial education
        assert "investment" in content.lower()
        assert "education" in content.lower() or "learning" in content.lower()
        # Check for visualization/plotting
        assert "plot" in content.lower() or "visualization" in content.lower() or "chart" in content.lower()
    
    def test_code_performance_content_structure(self, skills_loader):
        """Test that code-performance skill has expected sections."""
        content = skills_loader.load_skill("code-performance")
        
        # Check for multiple language support
        assert "Python" in content
        assert "JavaScript" in content or "Node.js" in content
        # Check for data engineering
        assert "Data Engineering" in content or "metrics" in content.lower()
        # Check for profiling tools
        assert "profil" in content.lower()
    
    def test_test_generator_content_structure(self, skills_loader):
        """Test that test-generator skill has expected sections."""
        content = skills_loader.load_skill("test-generator")
        
        # Check for multiple framework support
        assert "pytest" in content
        assert "Jest" in content
        assert "JUnit" in content or "Java" in content
        # Check for test patterns
        assert "Edge cases" in content or "edge case" in content.lower()
        assert "Happy path" in content or "happy path" in content.lower()
