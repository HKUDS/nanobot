from pathlib import Path

README = Path(__file__).resolve().parents[1] / "examples" / "skills" / "README.md"


def test_examples_skills_readme_exists():
    assert README.is_file()


def test_examples_skills_readme_documents_purpose():
    text = README.read_text(encoding="utf-8").lower()
    assert "not loaded by default" in text
    assert "weather" in text
    assert "copy" in text
