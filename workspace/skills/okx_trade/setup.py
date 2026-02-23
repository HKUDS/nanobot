#!/usr/bin/env python3
"""Setup script for OKX trading skill."""

import shutil
from pathlib import Path


def main():
    """Setup OKX trading skill configuration."""
    # Paths
    project_dir = Path(__file__).parent
    user_dir = Path.home() / ".nanobot" / "workspace" / "skills" / "okx_trade"

    # Create user directory
    user_dir.mkdir(parents=True, exist_ok=True)
    print(f"✓ Created directory: {user_dir}")

    # Copy config template if not exists
    user_config = user_dir / "config.json"
    if user_config.exists():
        print(f"⚠ Config already exists: {user_config}")
        print("  Skipping to avoid overwriting your settings")
    else:
        example_config = project_dir / "config.example.json"
        shutil.copy(example_config, user_config)
        print(f"✓ Created config: {user_config}")
        print()
        print("=" * 60)
        print("Next steps:")
        print("=" * 60)
        print(f"1. Edit the config file: nano {user_config}")
        print("2. Fill in your OKX API credentials:")
        print("   - api_key")
        print("   - secret_key")
        print("   - passphrase")
        print("3. Set is_demo to false when ready for live trading")
        print()
        print("Get API keys at: https://www.okx.com/account/my-api")
        print("=" * 60)


if __name__ == "__main__":
    main()
