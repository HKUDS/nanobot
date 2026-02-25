from typing import List, TypedDict


class Permission(TypedDict):
    type: int
    specify_role_ids: List[str]
    specify_user_ids: List[str]


class RenderData(TypedDict):
    label: str
    visited_label: str
    style: int


class Action(TypedDict):
    type: int
    permission: Permission
    click_limit: int
    data: str
    at_bot_show_channel_list: bool


class Button(TypedDict):
    id: str
    render_data: RenderData
    action: Action


class KeyboardRow(TypedDict):
    buttons: List[Button]


class Keyboard(TypedDict):
    rows: List[KeyboardRow]
