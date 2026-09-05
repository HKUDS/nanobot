import asyncio
import unittest

from nanobot.agent.goal_permission import (
    goal_mutation_allowed,
    goal_mutation_permission,
    revoke_goal_mutation_permission,
)


class GoalPermissionTests(unittest.IsolatedAsyncioTestCase):
    def test_nested_scope_restores_active_outer_grant(self) -> None:
        self.assertIs(goal_mutation_allowed(), False)
        with goal_mutation_permission(True):
            self.assertIs(goal_mutation_allowed(), True)
            with goal_mutation_permission(False):
                self.assertIs(goal_mutation_allowed(), False)
            self.assertIs(goal_mutation_allowed(), True)
        self.assertIs(goal_mutation_allowed(), False)

    async def test_permission_created_in_scope_expires_for_child_after_scope_exit(self) -> None:
        ready = asyncio.Event()
        release = asyncio.Event()

        async def child() -> bool:
            ready.set()
            await release.wait()
            return goal_mutation_allowed()

        with goal_mutation_permission(True):
            task = asyncio.create_task(child())
            await ready.wait()

        release.set()

        self.assertIs(await task, False)

    async def test_revoke_invalidates_permission_in_inherited_child_context(self) -> None:
        ready = asyncio.Event()
        release = asyncio.Event()

        async def child() -> bool:
            ready.set()
            await release.wait()
            return goal_mutation_allowed()

        with goal_mutation_permission(True):
            task = asyncio.create_task(child())
            await ready.wait()
            revoke_goal_mutation_permission()
            release.set()
            self.assertIs(await task, False)

    async def test_concurrent_scopes_do_not_revoke_each_other(self) -> None:
        first_ready = asyncio.Event()
        second_ready = asyncio.Event()
        release_first = asyncio.Event()
        release_second = asyncio.Event()

        async def scoped(ready: asyncio.Event, release: asyncio.Event) -> bool:
            with goal_mutation_permission(True):
                ready.set()
                await release.wait()
                return goal_mutation_allowed()

        first = asyncio.create_task(scoped(first_ready, release_first))
        second = asyncio.create_task(scoped(second_ready, release_second))
        await first_ready.wait()
        await second_ready.wait()

        release_first.set()
        self.assertIs(await first, True)
        release_second.set()
        self.assertIs(await second, True)
