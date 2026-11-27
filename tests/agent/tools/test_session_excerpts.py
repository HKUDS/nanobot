import json
from pathlib import Path

import pytest

from nanobot.agent.tools.sessions import ReadSessionTool, SearchSessionsTool
from nanobot.session.manager import SessionManager


@pytest.mark.parametrize("read_session,limit", [(False, 360), (True, 4_000)])
@pytest.mark.parametrize(
    "prefix,matched_text,query",
    [
        ("Straße ", "TARGET", "target"),
        ("ﬃ ", "Straße", "STRASSE"),
        ("x ", "ß", "s"),
        ("ordinary ", "TARGET", "target"),
    ],
)
async def test_session_excerpt_retains_casefold_match(
    tmp_path: Path, read_session: bool, limit: int,
    prefix: str, matched_text: str, query: str,
) -> None:
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("custom:unicode-excerpt")
    content = prefix * limit + matched_text + " " + "z" * (limit * 2)
    session.add_message("user", content)
    manager.save(session)

    if read_session:
        response = await ReadSessionTool(manager).execute(session_key=session.key, query=query)
        excerpt = json.loads(response)["messages"][0]["content"]
    else:
        response = await SearchSessionsTool(manager).execute(query=query)
        excerpt = json.loads(response)["results"][0]["excerpts"][0]["content"]

    assert matched_text in excerpt
    assert len(excerpt) <= limit + 2
    assert content not in excerpt
