"""Offline activation guard; outputs only presence/status, never secrets/events."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .caldav_io import credentials
from .config import Config


def validate(config_path: Path) -> None:
    from nanobot.config.loader import load_config
    from nanobot.triggers.local_store import LocalTriggerStore

    config = Config.load(config_path)
    if not config.nanobot_config_path:
        raise ValueError('Use the WebUI-generated config with nanobot_config_path')
    credentials(config.nanobot_config_path)
    gateway = load_config(Path(config.nanobot_config_path))
    trigger = LocalTriggerStore(Path(config.workspace_path)).get(config.trigger_id)
    if trigger is None or not trigger.enabled:
        raise ValueError('An enabled notification trigger is required')
    channel = getattr(gateway.channels, trigger.channel, {})
    shared = channel.get('technical', {}) if isinstance(channel, dict) else {}
    owner = shared.get('mainChatId', shared.get('main_chat_id', ''))
    shared_enabled = shared.get('sharedInbox', shared.get('shared_inbox', False))
    if shared_enabled:
        if (trigger.channel != 'telegram' or trigger.chat_id != owner
                or trigger.session_key != f'telegram-notifications:{owner}'):
            raise ValueError('Shared calendar notifications require the isolated owner notification session')
    elif gateway.agents.defaults.unified_session and trigger.session_key != 'unified:default':
        raise ValueError('Notification trigger must be bound to unified:default')
    if not isinstance(channel, dict) or not channel.get('enabled'):
        raise ValueError('Notification channel is not enabled')
    if trigger.channel == 'telegram':
        from nanobot.pairing import get_approved
        allowed = channel.get('allowFrom', channel.get('allow_from', []))
        if trigger.chat_id not in set(allowed) | set(get_approved('telegram')):
            raise ValueError('Telegram notification recipient must be explicitly approved')
        technical = channel.get('technical', {})
        technical_target = technical.get('chatId', technical.get('chat_id'))
        technical_token = technical.get('token') or channel.get('token', '')
        same_bot = technical_token.split(':', 1)[0] == channel.get('token', '').split(':', 1)[0]
        if technical.get('enabled') and same_bot and trigger.chat_id == technical_target:
            raise ValueError('Calendar notifications cannot use the technical feed')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    try:
        validate(args.config)
    except Exception as exc:
        # Third-party exceptions might contain credentials. Do not include str(exc).
        print(json.dumps({'ok': False, 'error_type': type(exc).__name__,
                          'action': 'Check saved credentials, enabled channel and unified trigger route'}))
        return 1
    print(json.dumps({'ok': True, 'offline_only': True,
                      'connection_and_delivery_test_still_required': True}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
