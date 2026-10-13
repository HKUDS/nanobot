from nanobot.llm_usage.context import source_from_request


def test_automation_metadata_overrides_user_session_source() -> None:
    assert source_from_request(
        "websocket:ordinary-session",
        channel="websocket",
        metadata={"_cron_trigger": {"job_id": "job"}},
    ) == "cron"
    assert source_from_request(
        "websocket:ordinary-session",
        channel="websocket",
        metadata={"_local_trigger": {"trigger_id": "trigger"}},
    ) == "cron"


def test_api_and_system_channels_have_explicit_sources() -> None:
    assert source_from_request("shared-session", channel="api", metadata={}) == "api"
    assert source_from_request("shared-session", channel="system", metadata={}) == "system"
