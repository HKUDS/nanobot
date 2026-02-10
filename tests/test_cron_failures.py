
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import time
import datetime

from nanobot.cron.types import CronJob, CronSchedule, CronPayload
from nanobot.cli.commands import execute_cron_job

class TestCronFailures(unittest.IsolatedAsyncioTestCase):
    
    async def test_empty_agent_response_raises_error(self):
        """
        Verify that if agent returns empty string for a delivery job,
        we raise an exception so the job status becomes 'error' (not 'ok').
        """
        # Setup
        job = CronJob(
            id="test", name="test",
            payload=CronPayload(
                kind="agent_turn",
                message="Think about life",
                deliver=True,
                to="user1",
                channel="telegram"
            )
        )
        
        bus = MagicMock()
        bus.publish_outbound = AsyncMock()
        
        agent = MagicMock()
        # Agent returns empty string
        agent.process_direct = AsyncMock(return_value="") 
        
        # Execute & Verify
        # Should raise ValueError to signal failure to CronService
        with self.assertRaises(ValueError):
            await execute_cron_job(job, bus, agent)
        
        # CRITICAL: Should send fallback message
        bus.publish_outbound.assert_called_once()
        call_args = bus.publish_outbound.call_args[0][0]
        self.assertEqual(call_args.content, "⚠️ Agent produced empty response.")
        
    async def test_echo_mode_bypasses_agent(self):
        """
        Verify that kind='echo' sends message directly without agent.
        """
        job = CronJob(
            id="test_echo", name="test_echo",
            payload=CronPayload(
                kind="echo",
                message="Drink water",
                deliver=True, # implied for echo if 'to' is present
                to="user1",
                channel="telegram"
            )
        )
        
        bus = MagicMock()
        bus.publish_outbound = AsyncMock()
        agent = MagicMock()
        
        # Execute
        await execute_cron_job(job, bus, agent)
        
        # Verify agent NOT called
        agent.process_direct.assert_not_called()
        
        # Verify message sent
        bus.publish_outbound.assert_called_once()
        call_args = bus.publish_outbound.call_args[0][0]
        self.assertEqual(call_args.content, "Drink water")
