from types import SimpleNamespace

import pytest

from time_manager import preflight


def setup(monkeypatch, tmp_path, *, session='unified:default', channel='websocket', enabled=True):
    from nanobot.config.schema import Config
    from nanobot.triggers.local_store import LocalTriggerStore
    cfg = preflight.Config(nanobot_config_path=str(tmp_path / 'nanobot.json'),
                           workspace_path=str(tmp_path), trigger_id='fixture',
                           management_calendar='Nanobot')
    monkeypatch.setattr(preflight.Config, 'load', lambda path: cfg)
    monkeypatch.setattr(preflight, 'credentials', lambda path: ('fixture-user', 'fixture-password', 'https://caldav.icloud.com/'))
    main = Config()
    main.agents.defaults.unified_session = True
    main.channels.websocket = {'enabled': True}
    main.channels.telegram = {'enabled': True, 'allowFrom': ['123']}
    monkeypatch.setattr('nanobot.config.loader.load_config', lambda path: main)
    trigger = SimpleNamespace(enabled=enabled, session_key=session, channel=channel, chat_id='123')
    monkeypatch.setattr(LocalTriggerStore, 'get', lambda self, tid: trigger)
    return tmp_path / 'webui.toml', main


def test_preflight_valid_route(monkeypatch, tmp_path):
    path, _ = setup(monkeypatch, tmp_path)
    preflight.validate(path)


def test_preflight_rejects_old_session(monkeypatch, tmp_path):
    path, _ = setup(monkeypatch, tmp_path, session='websocket:old')
    with pytest.raises(ValueError, match='unified'):
        preflight.validate(path)


def test_preflight_rejects_disabled_trigger(monkeypatch, tmp_path):
    path, _ = setup(monkeypatch, tmp_path, enabled=False)
    with pytest.raises(ValueError, match='enabled notification'):
        preflight.validate(path)


def test_preflight_rejects_disabled_channel(monkeypatch, tmp_path):
    path, main = setup(monkeypatch, tmp_path)
    main.channels.websocket['enabled'] = False
    with pytest.raises(ValueError, match='channel is not enabled'):
        preflight.validate(path)


def test_preflight_requires_credentials(monkeypatch, tmp_path):
    path, _ = setup(monkeypatch, tmp_path)
    def missing(path):
        raise RuntimeError('missing')
    monkeypatch.setattr(preflight, 'credentials', missing)
    with pytest.raises(RuntimeError, match='missing'):
        preflight.validate(path)


def test_preflight_approved_telegram(monkeypatch, tmp_path):
    path, _ = setup(monkeypatch, tmp_path, channel='telegram')
    monkeypatch.setattr('nanobot.pairing.get_approved', lambda channel: [])
    preflight.validate(path)


def test_preflight_unapproved_telegram(monkeypatch, tmp_path):
    path, main = setup(monkeypatch, tmp_path, channel='telegram')
    main.channels.telegram['allowFrom'] = []
    monkeypatch.setattr('nanobot.pairing.get_approved', lambda channel: [])
    with pytest.raises(ValueError, match='explicitly approved'):
        preflight.validate(path)


def test_preflight_rejects_technical_route(monkeypatch, tmp_path):
    path, main = setup(monkeypatch, tmp_path, channel='telegram')
    main.channels.telegram['technical'] = {'enabled': True, 'chatId': '123'}
    monkeypatch.setattr('nanobot.pairing.get_approved', lambda channel: [])
    with pytest.raises(ValueError, match='technical feed'):
        preflight.validate(path)


def test_preflight_shared_notifications_are_isolated(monkeypatch, tmp_path):
    path, main = setup(monkeypatch, tmp_path, channel='telegram', session='telegram-notifications:123')
    main.channels.telegram['technical'] = {'sharedInbox': True, 'mainChatId': '123'}
    monkeypatch.setattr('nanobot.pairing.get_approved', lambda channel: [])
    preflight.validate(path)


@pytest.mark.parametrize('session', ['unified:default', 'telegram:123', 'telegram-notifications:456'])
def test_preflight_shared_rejects_other_session(monkeypatch, tmp_path, session):
    path, main = setup(monkeypatch, tmp_path, channel='telegram', session=session)
    main.channels.telegram['technical'] = {'sharedInbox': True, 'mainChatId': '123'}
    with pytest.raises(ValueError, match='isolated owner'):
        preflight.validate(path)


def test_preflight_distinct_notification_bot_does_not_block_main_bot(monkeypatch, tmp_path):
    path, main = setup(monkeypatch, tmp_path, channel='telegram')
    main.channels.telegram['token'] = '111:fixture'
    main.channels.telegram['technical'] = {'enabled': True, 'chatId': '123', 'token': '222:fixture'}
    monkeypatch.setattr('nanobot.pairing.get_approved', lambda channel: [])
    preflight.validate(path)
