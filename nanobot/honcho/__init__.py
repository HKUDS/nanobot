"""Honcho integration for AI-native memory.

This package is only active when honcho.enabled=true in config and
HONCHO_API_KEY is set. All honcho-ai imports are deferred to avoid
ImportError when the package is not installed.
"""
