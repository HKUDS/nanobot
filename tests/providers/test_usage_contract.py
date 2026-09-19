import pytest

from nanobot.providers.base import LLMUsage


def test_reported_usage_derives_total_and_preserves_unreported_cache() -> None:
    usage = LLMUsage.reported(input_tokens=12, output_tokens=3)

    assert usage.total_tokens == 15
    assert usage.cache_read_tokens is None
    assert usage.cache_write_tokens is None
    assert usage.source == "reported"


def test_reported_usage_preserves_explicit_total_across_contract_operations() -> None:
    usage = LLMUsage.reported(input_tokens=15, output_tokens=18, total_tokens=175)

    assert usage.total_tokens == 175
    assert usage.reported_tokens == 175
    assert usage.estimated_tokens == 0
    assert LLMUsage.from_dict(usage.to_dict()) == usage
    assert usage.with_timing(generation_ms=25, ttft_ms=5).total_tokens == 175

    combined = usage + LLMUsage.estimated(input_tokens=2, output_tokens=1)
    assert combined.total_tokens == 178
    assert combined.reported_tokens == 175
    assert combined.estimated_tokens == 3


def test_reported_usage_normalizes_missing_or_underreported_total() -> None:
    missing = LLMUsage.reported(input_tokens=15, output_tokens=18)
    underreported = LLMUsage.reported(
        input_tokens=15,
        output_tokens=18,
        total_tokens=12,
    )

    assert missing.total_tokens == 33
    assert underreported.total_tokens == 33
    assert underreported.reported_tokens == 33


def test_reported_usage_preserves_explicit_zero_cache() -> None:
    usage = LLMUsage.reported(
        input_tokens=12,
        output_tokens=3,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )

    assert usage.cache_read_tokens == 0
    assert usage.cache_write_tokens == 0


def test_usage_rejects_inconsistent_token_partitions_and_cache_totals() -> None:
    with pytest.raises(ValueError, match="must equal"):
        LLMUsage(input_tokens=10, output_tokens=2, total_tokens=12, reported_tokens=11)

    with pytest.raises(ValueError, match="at least"):
        LLMUsage(input_tokens=10, output_tokens=2, total_tokens=11, reported_tokens=11)

    with pytest.raises(ValueError, match="cache token counts"):
        LLMUsage.reported(input_tokens=10, output_tokens=2, cache_read_tokens=11)


def test_usage_serialization_is_strict_and_rejects_legacy_or_tampered_data() -> None:
    usage = LLMUsage.estimated(input_tokens=10, output_tokens=2)
    serialized = usage.to_dict()

    assert LLMUsage.from_dict(serialized) == usage
    assert LLMUsage.from_dict({"prompt_tokens": 10, "completion_tokens": 2}) is None
    assert LLMUsage.from_dict({**serialized, "total_tokens": 99}) is None
    assert LLMUsage.from_dict({**serialized, "source": "reported"}) is None
    assert LLMUsage.from_dict({**serialized, "legacy_alias": 12}) is None


def test_usage_aggregation_keeps_reported_estimated_split_and_unknown_cache() -> None:
    reported = LLMUsage.reported(
        input_tokens=10,
        output_tokens=2,
        total_tokens=20,
        cache_read_tokens=4,
    )
    estimated = LLMUsage.estimated(input_tokens=5, output_tokens=1)

    combined = reported + estimated

    assert combined.input_tokens == 15
    assert combined.output_tokens == 3
    assert combined.total_tokens == 26
    assert combined.reported_tokens == 20
    assert combined.estimated_tokens == 6
    assert combined.source == "mixed"
    assert combined.cache_read_tokens is None
    assert combined.context_tokens == 5
    assert combined.request_count == 2


def test_usage_projects_compact_turn_observability_shape() -> None:
    usage = LLMUsage.reported(
        input_tokens=12,
        output_tokens=3,
        total_tokens=20,
        cache_read_tokens=4,
    ).with_timing(generation_ms=250, ttft_ms=50) + LLMUsage.estimated(
        input_tokens=18,
        output_tokens=2,
    ).with_timing(generation_ms=100, ttft_ms=None)

    assert usage.to_turn_dict() == {
        "prompt_tokens": 30,
        "completion_tokens": 5,
        "total_tokens": 40,
        "context_tokens": 18,
        "request_count": 2,
        "estimated_tokens": 20,
        "generation_ms": 350,
        "measured_completion_tokens": 5,
        "ttft_ms": 50,
        "timed_requests": 1,
    }


def test_empty_request_counts_without_replacing_last_context() -> None:
    usage = LLMUsage.reported(input_tokens=12, output_tokens=3) + LLMUsage.empty_request()

    assert usage.total_tokens == 15
    assert usage.context_tokens == 12
    assert usage.request_count == 2
