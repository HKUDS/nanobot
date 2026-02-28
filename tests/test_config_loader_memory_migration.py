import json
from pathlib import Path

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


def test_load_migrates_legacy_gemini_to_embedding(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "agents": {
                    "memory": {
                        "gemini": {
                            "apiKey": "g-key",
                            "apiBase": "https://generativelanguage.googleapis.com/v1beta",
                            "model": "models/gemini-embedding-001",
                            "outputDimensionality": 768,
                            "timeoutS": 30,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)
    assert cfg.agents.memory.embedding.provider == "gemini"
    assert cfg.agents.memory.embedding.api_key == "g-key"


def test_save_hides_legacy_gemini_block(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg = Config()
    cfg.agents.memory.embedding.api_key = "e-key"

    save_config(cfg, cfg_path)
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    memory = (data.get("agents") or {}).get("memory") or {}

    assert "embedding" in memory
    assert "gemini" not in memory
