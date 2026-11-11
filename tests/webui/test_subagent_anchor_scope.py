import pytest

from nanobot.webui.ws_http import GatewayHTTPHandler


@pytest.mark.parametrize("query", [
    "scope=unlinked", "scope=page&message_id=m", "scope=page&turn_id=t",
    "message_id=m", "turn_id=t", "task_id=t",
])
def test_legacy_origin_queries_are_rejected(query):
    with pytest.raises(ValueError):
        GatewayHTTPHandler._subagent_history_scope("/subagents?" + query)


def test_explicit_anchor_task_ids_are_accepted():
    scope = GatewayHTTPHandler._subagent_history_scope("/subagents?scope=page&task_id=one&task_id=two")
    assert scope is not None
    assert scope.task_ids == {"one", "two"}
