#!/usr/bin/env python3
"""
Minimal validator for nanobot skill folders (CLI entry).

Implementation lives in :mod:`nanobot.agent.skill_validation`.
"""

import sys

from nanobot.agent.skill_validation import validate_skill

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        sys.exit(1)

    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)
