import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronSchedule, CronPayload, CronJobState
from nanobot.bus.events import OutboundMessage
from nanobot.cli.commands import execute_cron_job

class TestCronAgentIntegration(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.store_path = MagicMock(spec=Path)
        self.store_path.exists.return_value = False
        self.service = CronService(self.store_path)
        
        self.bus = MagicMock()
        self.bus.publish_outbound = AsyncMock()
        
        self.agent = MagicMock()
        self.agent.process_direct = AsyncMock()

    # 1. Test Batch Add
    async def test_batch_add(self):
        print("\n[Test] Batch Add")
        jobs_data = [
            {
                "name": "echo1",
                "message": "hello",
                "schedule": CronSchedule(kind="every", every_ms=1000),
                "kind": "echo",
                "deliver": True,
                "channel": "tg",
                "to": "123"
            },
            {
                "name": "agent1",
                "message": "think",
                "schedule": CronSchedule(kind="every", every_ms=2000),
                "kind": "agent_turn",
                "deliver": True,
                "channel": "tg",
                "to": "123"
            }
        ]
        
        created = await self.service.add_jobs_batch(jobs_data)
        
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].name, "echo1")
        self.assertEqual(created[0].payload.kind, "echo")
        self.assertEqual(created[1].name, "agent1")
        self.assertEqual(created[1].payload.kind, "agent_turn")
        print("  ✓ Batch added successfully")

    # 2. Test Echo Execution
    async def test_echo_execution(self):
        print("\n[Test] Echo Execution")
        job = CronJob(
            id="j1", name="echo_job", enabled=True,
            schedule=CronSchedule(kind="every", every_ms=1000),
            payload=CronPayload(
                kind="echo",
                message="Echo Message",
                deliver=True, channel="tg", to="123"
            ),
            state=CronJobState(),
            created_at_ms=0,
            updated_at_ms=0
        )
        
        result = await execute_cron_job(job, self.bus, self.agent)
        
        # Verify result
        self.assertEqual(result, "Echo Message")
        
        # Verify published
        self.bus.publish_outbound.assert_called_once()
        msg = self.bus.publish_outbound.call_args[0][0]
        self.assertIsInstance(msg, OutboundMessage)
        self.assertEqual(msg.content, "Echo Message")
        self.assertEqual(msg.channel, "tg")
        self.assertEqual(msg.chat_id, "123")
        
        # Verify agent NOT called
        self.agent.process_direct.assert_not_called()
        print("  ✓ Echo executed correctly (No agent call)")

    # 3. Test Agent Execution
    async def test_agent_execution(self):
        print("\n[Test] Agent Execution")
        job = CronJob(
            id="j2", name="agent_job", enabled=True,
            schedule=CronSchedule(kind="every", every_ms=1000),
            payload=CronPayload(
                kind="agent_turn",
                message="Do something",
                deliver=True, channel="tg", to="123"
            ),
            state=CronJobState(),
            created_at_ms=0,
            updated_at_ms=0
        )
        
        # Mock Agent Response
        self.agent.process_direct.return_value = "Agent Result"
        
        result = await execute_cron_job(job, self.bus, self.agent)
        
        # Verify result
        self.assertEqual(result, "Agent Result")
        
        # Verify published
        self.bus.publish_outbound.assert_called_once()
        msg = self.bus.publish_outbound.call_args[0][0]
        self.assertEqual(msg.content, "Agent Result")
        
        # Verify agent called
        self.agent.process_direct.assert_called_once()
        print("  ✓ Agent executed and result delivered")

    # 4. Test Empty Agent Response (Safety)
    async def test_agent_empty_response(self):
        print("\n[Test] Agent Empty Response")
        job = CronJob(
            id="j3", name="agent_empty", enabled=True,
            schedule=CronSchedule(kind="every", every_ms=1000),
            payload=CronPayload(
                kind="agent_turn",
                message="Do something",
                deliver=True, channel="tg", to="123"
            ),
            state=CronJobState(),
            created_at_ms=0,
            updated_at_ms=0
        )
        
        self.agent.process_direct.return_value = ""
        
        # Should raise ValueError or handle it
        with self.assertRaises(ValueError):
            await execute_cron_job(job, self.bus, self.agent)
            
        # Verify warning message sent
        self.bus.publish_outbound.assert_called_once()
        msg = self.bus.publish_outbound.call_args[0][0]
        self.assertIn("empty response", msg.content)
        print("  ✓ Empty response handled safely")

if __name__ == "__main__":
    unittest.main()
