"""X list tools — create, delete, get, owned, add/remove member via coordinator API."""

from typing import Any

from nanobot.agent.tools.x.base import XBaseTool


class XCreateListTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_create_list"

    @property
    def description(self) -> str:
        return (
            "Create a new list on X. "
            "Authentication is automatic — never ask the user for credentials, tokens, or bot_id.\n\n"
            "DISPLAY FORMAT: Include this directive when confirming the created list:\n"
            '::x-list{name="<list_name>" url="https://x.com/i/lists/<list_id>" members="0 members" size="default"}\n'
            "Replace placeholders with actual values from the response.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the list."},
                "description": {"type": "string", "description": "Optional description for the list."},
                "private": {"type": "boolean", "description": "Whether the list is private (default false)."},
            },
            "required": ["name"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload: dict[str, Any] = {"bot_id": bot_id, "name": kwargs["name"]}
        if kwargs.get("description"):
            payload["description"] = kwargs["description"]
        if kwargs.get("private") is not None:
            payload["private"] = kwargs["private"]
        return await self._post(f"{coordinator_url}/internal/x/lists/create", payload)


class XDeleteListTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_delete_list"

    @property
    def description(self) -> str:
        return "Delete a list on X by its ID. Authentication is automatic."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "The ID of the list to delete."},
            },
            "required": ["list_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "list_id": kwargs["list_id"]}
        return await self._post(f"{coordinator_url}/internal/x/lists/delete", payload)


class XGetListTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_list"

    @property
    def description(self) -> str:
        return (
            "Get details of an X list by its ID. Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include this directive when presenting the list:\n"
            '::x-list{name="<list_name>" description="<list_description>" url="https://x.com/i/lists/<list_id>" members="<member_count> members" size="default"}\n'
            "Replace placeholders with actual values. Omit description if not available.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "The ID of the list to retrieve."},
            },
            "required": ["list_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "list_id": kwargs["list_id"]}
        return await self._post(f"{coordinator_url}/internal/x/lists/get", payload)


class XGetOwnedListsTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_owned_lists"

    @property
    def description(self) -> str:
        return (
            "Get all lists owned by the authenticated X user. Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include a directive for EACH list in your response:\n"
            '::x-list{name="<list_name>" url="https://x.com/i/lists/<list_id>" members="<member_count> members" size="compact"}\n'
            "Use compact size when listing multiple lists. Replace placeholders with actual values from each list.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id}
        return await self._post(f"{coordinator_url}/internal/x/lists/owned", payload)


class XAddListMemberTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_add_list_member"

    @property
    def description(self) -> str:
        return "Add a user to an X list. Authentication is automatic."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "The ID of the list."},
                "user_id": {"type": "string", "description": "The X user ID to add as a member."},
            },
            "required": ["list_id", "user_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "list_id": kwargs["list_id"], "user_id": kwargs["user_id"]}
        return await self._post(f"{coordinator_url}/internal/x/lists/add-member", payload)


class XRemoveListMemberTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_remove_list_member"

    @property
    def description(self) -> str:
        return "Remove a user from an X list. Authentication is automatic."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "The ID of the list."},
                "user_id": {"type": "string", "description": "The X user ID to remove."},
            },
            "required": ["list_id", "user_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "list_id": kwargs["list_id"], "user_id": kwargs["user_id"]}
        return await self._post(f"{coordinator_url}/internal/x/lists/remove-member", payload)
