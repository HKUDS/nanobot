import pytest

from nanobot.agent.handoff import HandoffRouter
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.session.manager import SessionManager


class DummyAgent:
    def __init__(self, name: str, workspace, response: str):
        self.agent_name = name
        self.model = f"model-{name}"
        self.sessions = SessionManager(workspace)
        self._response = response

    async def _process_message(self, msg: InboundMessage, session_key: str | None = None) -> OutboundMessage:
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=self._response)


@pytest.mark.asyncio
async def test_handoff_routes_and_syncs_session(tmp_path) -> None:
    source = DummyAgent("default", tmp_path / "default", "from default")
    target = DummyAgent("coder", tmp_path / "coder", "from coder")

    router = HandoffRouter({"default": source, "coder": target}, default_name="default")

    session_key = "cli:direct"
    session = source.sessions.get_or_create(session_key)
    session.add_message("user", "hello")
    source.sessions.save(session)

    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="handoff please")
    outcome = await router.handoff("default", "coder", msg, session_key=session_key)

    assert router.route_for(session_key) == "coder"
    assert outcome.response is not None
    assert outcome.response.content == "from coder"

    target_session = target.sessions.get_or_create(session_key)
    assert target_session.messages
    assert target_session.metadata["handoff_synced_from"] == "default"
