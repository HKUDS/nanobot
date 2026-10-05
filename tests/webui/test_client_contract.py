"""Published package versions never substitute for wire compatibility."""

import pytest

from nanobot.webui.client_contract import assess_webui_contract, compatibility_error, webui_contract


def test_initial_host_declaration_is_an_independent_wire_fixture():
    # Frozen initial host payload; intentionally not built using the current producer.
    initial_host = {
        "version": "0.3.5",
        "min_protocol": 1,
        "max_protocol": 1,
        "capabilities": ["webui.core.v1"],
    }
    assert assess_webui_contract(initial_host)["status"] == "compatible"


def test_current_producer_remains_acceptable_to_initial_client():
    # Initial client's advertised requirement, independent of today's constants.
    contract = webui_contract()
    assert contract["min_protocol"] <= 1 <= contract["max_protocol"]
    assert "webui.core.v1" in contract["capabilities"]


@pytest.mark.parametrize("version", ["0.0.1", "9.99.0", "0.3.5.dev17", "custom-build"])
def test_independently_released_hosts_share_a_protocol(version):
    report = assess_webui_contract({**webui_contract(), "version": version})
    assert report["status"] == "compatible"
    assert report["host_version"] == version
    assert compatibility_error(report) == ""


@pytest.mark.parametrize("value", [None, {}, "1", {"min_protocol": True, "max_protocol": 1},
    {"min_protocol": 2, "max_protocol": 1, "capabilities": []},
    {"min_protocol": 1, "max_protocol": 1, "capabilities": "webui.core.v1"},
    {"min_protocol": 1, "max_protocol": 1, "capabilities": [123]},
])
def test_missing_or_malformed_metadata_is_unknown_not_outdated(value):
    report = assess_webui_contract(value)
    assert report["status"] == "unknown"
    assert compatibility_error(report) == "webui_compatibility_unknown"


def test_new_host_can_explicitly_retain_old_protocol_support():
    assert assess_webui_contract({**webui_contract(), "max_protocol": 2})["status"] == "compatible"


def test_recovery_targets_the_correct_machine():
    future = {**webui_contract(), "min_protocol": 2, "max_protocol": 2}
    assert compatibility_error(assess_webui_contract(future)) == "client_update_required"
    missing = {**webui_contract(), "capabilities": []}
    assert compatibility_error(assess_webui_contract(missing)) == "host_update_required"


def test_unknown_optional_capabilities_do_not_break_connection():
    value = webui_contract()
    value["capabilities"] = ["webui.core.v1", "a-future-optional-feature"]
    assert assess_webui_contract(value)["status"] == "compatible"
