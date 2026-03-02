"""Profile management for multiple AI accounts."""

import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict
from loguru import logger
from nanobot.config.loader import get_data_dir


class Profile(BaseModel):
    """A definition for a user's AI account profile."""
    name: str
    model: str
    api_key: str
    api_base: str | None = None
    
    model_config = ConfigDict(extra="ignore")


class ProfileManager:
    """Manages reading and writing profiles to a JSON file."""
    
    def __init__(self, store_path: Path | None = None):
        self.store_path = store_path or get_data_dir() / "profiles.json"
        
    def _read_profiles(self) -> dict[str, dict]:
        """Read raw dictionary of profiles from disk."""
        if not self.store_path.exists():
            return {}
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to read profiles from {}: {}", self.store_path, e)
            return {}
            
    def _write_profiles(self, profiles: dict[str, dict]) -> None:
        """Write raw dictionary of profiles to disk."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(profiles, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to write profiles to {}: {}", self.store_path, e)
            
    def get_profile(self, name: str) -> Profile | None:
        """Get a specific profile by name."""
        data = self._read_profiles()
        if name not in data:
            return None
        try:
            return Profile(**data[name])
        except Exception as e:
            logger.error("Failed to parse profile '{}': {}", name, e)
            return None
            
    def list_profiles(self) -> list[Profile]:
        """List all available profiles."""
        data = self._read_profiles()
        profiles = []
        for name, profile_data in data.items():
            try:
                profiles.append(Profile(**profile_data))
            except Exception as e:
                logger.warning("Skipping invalid profile '{}': {}", name, e)
        return profiles
        
    def add_profile(self, profile: Profile) -> None:
        """Add or update a profile."""
        data = self._read_profiles()
        data[profile.name] = profile.model_dump()
        self._write_profiles(data)
        
    def remove_profile(self, name: str) -> bool:
        """Remove a profile by name. Returns True if removed, False if not found."""
        data = self._read_profiles()
        if name in data:
            del data[name]
            self._write_profiles(data)
            return True
        return False
