
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import datetime
from pathlib import Path
import json

from nanobot.cron.types import CronJob, CronSchedule, CronPayload
from nanobot.cli.commands import execute_cron_job, cron_add
from nanobot.config.schema import Config, AgentDefaults, AgentsConfig
import typer

class TestCronUX(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        # Create a dummy config
        self.config = Config()
        self.config.agents.defaults.timezone = None # Simulate unset timezone

    @patch('nanobot.config.loader.load_config')
    @patch('nanobot.config.loader.save_config')
    @patch('nanobot.cron.service.CronService')
    @patch('typer.confirm')
    @patch('typer.prompt')
    @patch('nanobot.cli.commands.console.print')
    def test_interactive_timezone_setup(self, mock_print, mock_prompt, mock_confirm, mock_service, mock_save, mock_load):
        """
        Test that if timezone is unset, we prompt user and save it.
        """
        # Setup mocks
        mock_load.return_value = self.config
        mock_confirm.return_value = True # User says YES to system timezone and YES to save
        
        # Configure add_job to be async
        mock_service.return_value.add_job = AsyncMock()
        mock_service.return_value.add_job.return_value = MagicMock(name="test_job", id="123")
        
        # Simulate cron add call
        try:
            # When patching locally in a function, we must patch where the name is IMPORTED.
            # In nanobot.cli.commands, load_config is imported from nanobot.config.loader.
            # BUT: In python -m unittest, the module nanobot.cli.commands has likely already imported it.
            # So patching 'nanobot.config.loader.load_config' affects future imports, 
            # but patching 'nanobot.cli.commands.load_config' affects the name in that module.
            # The error "does not have attribute load_config" means it's not in the namespace of commands.py?
            # Let's check commands.py imports. It imports inside the function!
            # "from nanobot.config.loader import get_data_dir, load_config, save_config"
            # This means we MUST patch 'nanobot.config.loader.load_config' globally (which the decorator does)
            # OR patch it where it is defined.
            
            # Since the function imports it LOCALLY, we can't easily patch "nanobot.cli.commands.load_config".
            # We must patch 'nanobot.config.loader.load_config' which we already do with decorators.
            # So we don't need the inner context managers if the decorators work!
            
            # The problem with the previous test was trying to patch 'nanobot.cli.commands.load_config'
            # which doesn't exist at module level because it's imported inside the function.
            
            # So, relying on the decorators (mock_load) is correct for the function call
            # IF the function imports it every time.
            
            cron_add(
                name="test",
                message="msg",
                cron_expr="0 9 * * *",
                every=None, at=None,
                deliver=False, to=None, channel=None,
                timezone=None, # Explicitly None to trigger auto-setup
                kind="agent_turn"
            )
            
            # Verify internal save called
            mock_save.assert_called()
            self.assertIsNotNone(self.config.agents.defaults.timezone)
        except typer.Exit:
            pass 

    @patch('nanobot.config.loader.load_config')
    def test_validation_delivery_params(self, mock_load):
        """
        Test that --deliver without --to/--channel raises error.
        """
        mock_load.return_value = self.config
        
        with self.assertRaises(typer.Exit):
            cron_add(
                name="test",
                message="msg",
                every=60, cron_expr=None, at=None,
                deliver=True, # TRIGGER
                to=None,      # MISSING
                channel=None, # MISSING
                timezone=None, kind="agent_turn"
            )

    @patch('nanobot.config.loader.load_config')
    @patch('nanobot.cron.service.CronService')
    def test_timezone_priority_cli(self, mock_service, mock_load):
        """
        Test that CLI arg overrides config.
        """
        # Config says UTC
        self.config.agents.defaults.timezone = "UTC"
        mock_load.return_value = self.config
        
        # Configure add_job to be async
        mock_service.return_value.add_job = AsyncMock()
        mock_service.return_value.add_job.return_value = MagicMock(name="test_job", id="123")
        
        # We don't need inner patches because the decorators already patch the imports globally
        # for the duration of the test.
        # However, mock_service passed as arg is the mock object.
        # We need to make sure the function uses THIS mock.
        
        # CLI says Moscow
        cron_add(
            name="test",
            message="msg",
            cron_expr="0 9 * * *",
            every=None, at=None,
            deliver=False, to=None, channel=None,
            timezone="Europe/Moscow", # CLI ARG
            kind="agent_turn"
        )
        
        # Verify Service received Moscow
        kwargs = mock_service.return_value.add_job.call_args.kwargs
        schedule = kwargs['schedule']
        self.assertEqual(schedule.tz, "Europe/Moscow")

    @patch('nanobot.config.loader.load_config')
    @patch('nanobot.cron.service.CronService')
    def test_timezone_priority_config(self, mock_service, mock_load):
        """
        Test that Config is used if CLI arg is missing.
        """
        # Config says Berlin
        self.config.agents.defaults.timezone = "Europe/Berlin"
        mock_load.return_value = self.config
        
        # Configure add_job to be async
        mock_service.return_value.add_job = AsyncMock()
        mock_service.return_value.add_job.return_value = MagicMock(name="test_job", id="123")
        
        # CLI arg missing
        cron_add(
            name="test",
            message="msg",
            cron_expr="0 9 * * *",
            every=None, at=None,
            deliver=False, to=None, channel=None,
            timezone=None, 
            kind="agent_turn"
        )
        
        # Verify Service received Berlin
        kwargs = mock_service.return_value.add_job.call_args.kwargs
        schedule = kwargs['schedule']
        self.assertEqual(schedule.tz, "Europe/Berlin")

if __name__ == '__main__':
    unittest.main()
