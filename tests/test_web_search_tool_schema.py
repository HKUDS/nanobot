import pytest

from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import SearxngSearchConfig, WebSearchConfig


def _props(tool: WebSearchTool) -> dict[str, object]:
    schema = tool.to_schema()
    return schema["function"]["parameters"]["properties"]


def test_schema_brave_only_includes_brave_params() -> None:
    cfg = WebSearchConfig(provider="brave", max_results=7, api_key="x")
    tool = WebSearchTool(config=cfg)

    props = _props(tool)
    assert set(props.keys()) == {"query", "count"}
    assert props["count"]["default"] == 7
    assert "Brave" in tool.to_schema()["function"]["description"]


def test_schema_searxng_includes_searxng_params() -> None:
    cfg = WebSearchConfig(
        provider="searxng",
        max_results=3,
        searxng=SearxngSearchConfig(
            base_url="https://searx.example.com",
            language="en",
            categories=["general"],
            safesearch=1,
            time_range="week",
            engines=["google", "bing"],
        ),
    )
    tool = WebSearchTool(config=cfg)

    props = _props(tool)
    assert {"language", "categories", "time_range", "safesearch", "engines"}.issubset(set(props.keys()))
    assert props["count"]["default"] == 3
    assert props["language"]["default"] == "en"
    assert props["categories"]["default"] == ["general"]
    assert props["time_range"]["default"] == "week"
    assert props["safesearch"]["default"] == 1
    assert props["engines"]["default"] == ["google", "bing"]
    assert "SearXNG" in tool.to_schema()["function"]["description"]


def test_schema_auto_prefers_searxng_when_base_url_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://searx.example.com")
    cfg = WebSearchConfig(provider="auto", max_results=2)
    tool = WebSearchTool(config=cfg)

    props = _props(tool)
    assert "language" in props
    assert "SearXNG" in tool.to_schema()["function"]["description"]


def test_schema_auto_falls_back_to_brave_without_searxng(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    cfg = WebSearchConfig(provider="auto", max_results=2)
    tool = WebSearchTool(config=cfg)

    props = _props(tool)
    assert set(props.keys()) == {"query", "count"}
    assert "Brave" in tool.to_schema()["function"]["description"]


def test_parameters_property_matches_schema_parameters_brave() -> None:
    cfg = WebSearchConfig(provider="brave", max_results=2, api_key="x")
    tool = WebSearchTool(config=cfg)
    assert tool.parameters == tool.to_schema()["function"]["parameters"]


def test_parameters_property_matches_schema_parameters_searxng() -> None:
    cfg = WebSearchConfig(
        provider="searxng",
        max_results=2,
        searxng=SearxngSearchConfig(base_url="https://searx.example.com"),
    )
    tool = WebSearchTool(config=cfg)
    assert tool.parameters == tool.to_schema()["function"]["parameters"]
