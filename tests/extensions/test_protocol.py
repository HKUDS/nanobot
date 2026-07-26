import pytest

from nanobot.extensions.protocol import NodeProtocolError, NodeRegistration


@pytest.mark.parametrize("field", ["kind", "name"])
def test_node_registration_rejects_blank_identity(field: str) -> None:
    value = {"kind": "tool", "name": "sample"}
    value[field] = " "

    with pytest.raises(NodeProtocolError, match="non-empty"):
        NodeRegistration.from_mapping(value)


@pytest.mark.parametrize(
    "kind",
    ("tool", "command"),
)
@pytest.mark.parametrize(
    "name",
    ("has space", "has.dot", "x" * 65),
)
def test_node_registration_rejects_unsafe_callable_names(
    kind: str,
    name: str,
) -> None:
    with pytest.raises(NodeProtocolError, match=f"{kind} name"):
        NodeRegistration.from_mapping({"kind": kind, "name": name})


def test_node_registration_rejects_non_object_tool_schema() -> None:
    with pytest.raises(NodeProtocolError, match="object schema"):
        NodeRegistration.from_mapping(
            {
                "kind": "tool",
                "name": "sample",
                "schema": {"type": "string"},
            }
        )
