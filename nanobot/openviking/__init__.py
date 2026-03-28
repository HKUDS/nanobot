"""OpenViking integration for nanobot — optional semantic memory layer."""

try:
    import openviking as _ov  # noqa: F401

    HAS_OPENVIKING = True
except Exception:
    HAS_OPENVIKING = False
