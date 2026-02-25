import asyncio
import inspect
from typing import List, Callable, Dict, Any, Optional

from .channel import Channel
from .guild import Guild
from .interaction import Interaction
from .manage import C2CManageEvent, GroupManageEvent
from .message import C2CMessage, GroupMessage, Message, DirectMessage, MessageAudit
from .user import Member
from .reaction import Reaction
from .audio import Audio, PublicAudio
from .forum import Thread, OpenThread

from . import logging
from .api import BotAPI
from .robot import Robot
from .types import session

_log = logging.get_logger()


class ConnectionSession:
    """Client的Websocket连接会话

    SessionPool主要支持session的重连,可以根据session的状态动态设置是否需要进行重连操作
    这里通过设置session_id=""空则任务session需要重连
    """

    def __init__(
        self,
        max_async,
        connect: Callable,
        dispatch: Callable,
        loop=None,
        api: BotAPI = None,
    ):
        self.dispatch = dispatch
        self.state = ConnectionState(dispatch, api)
        self.parser: Dict[str, Callable[[dict], None]] = self.state.parsers

        self._connect = connect
        self._max_async = max_async
        self.loop: asyncio.AbstractEventLoop = asyncio.get_event_loop() if loop is None else loop
        # session链接同时最大并发数
        self._session_list: List[session.Session] = []

    async def multi_run(self, session_interval=5):
        if len(self._session_list) == 0:
            return
        # 根据并发数同时建立多个future
        index = 0
        session_list = self._session_list
        # 需要执行的链接列表，通过time_interval控制启动时间
        tasks = []

        while len(session_list) > 0:
            _log.debug("[botpy] 会话列表循环运行")
            time_interval = session_interval * (index + 1)
            _log.info("[botpy] 最大并发连接数: %s, 启动会话数: %s" % (self._max_async, len(session_list)))
            for i in range(self._max_async):
                if len(session_list) == 0:
                    break
                tasks.append(asyncio.ensure_future(self._runner(session_list.pop(i), time_interval), loop=self.loop))
            index += self._max_async

        await asyncio.wait(tasks)

    async def _runner(self, session, time_interval):
        await self._connect(session)
        # 后台有频率限制，根据间隔时间发起链接请求
        await asyncio.sleep(time_interval)

    def add(self, _session: session.Session):
        self._session_list.append(_session)


class ConnectionState:
    """Client的Websocket状态处理"""

    def __init__(self, dispatch: Callable, api: BotAPI):
        self.robot: Optional[Robot] = None

        self.parsers: Dict[str, Callable[[Any], None]]
        self.parsers = {}
        for attr, func in inspect.getmembers(self):
            if attr.startswith("parse_"):
                self.parsers[attr[6:].lower()] = func

        self._dispatch = dispatch
        self.api = api

    def parse_ready(self, payload):
        self._dispatch("ready")

    def parse_resumed(self, payload):
        self._dispatch("resumed")

    # botpy.flags.Intents.guilds
    def parse_guild_create(self, payload):
        _guild = Guild(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("guild_create", _guild)

    def parse_guild_update(self, payload):
        _guild = Guild(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("guild_update", _guild)

    def parse_guild_delete(self, payload):
        _guild = Guild(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("guild_delete", _guild)

    def parse_channel_create(self, payload):
        _channel = Channel(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("channel_create", _channel)

    def parse_channel_update(self, payload):
        _channel = Channel(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("channel_update", _channel)

    def parse_channel_delete(self, payload):
        _channel = Channel(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("channel_delete", _channel)

    # botpy.flags.Intents.guild_members
    def parse_guild_member_add(self, payload):
        _member = Member(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("guild_member_add", _member)

    def parse_guild_member_update(self, payload):
        _member = Member(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("guild_member_update", _member)

    def parse_guild_member_remove(self, payload):
        _member = Member(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("guild_member_remove", _member)

    # botpy.flags.Intents.guild_messages
    def parse_message_create(self, payload):
        _message = Message(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("message_create", _message)

    def parse_message_delete(self, payload):
        _message = Message(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("message_delete", _message)

    # botpy.flags.Intents.guild_message_reactions
    def parse_message_reaction_add(self, payload):
        _reaction = Reaction(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("message_reaction_add", _reaction)

    def parse_message_reaction_remove(self, payload):
        _reaction = Reaction(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("message_reaction_remove", _reaction)

    # botpy.flags.Intents.direct_message
    def parse_direct_message_create(self, payload):
        _message = DirectMessage(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("direct_message_create", _message)

    def parse_direct_message_delete(self, payload):
        _message = DirectMessage(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("direct_message_delete", _message)

    # botpy.flags.Intents.interaction
    def parse_interaction_create(self, payload):
        _interaction = Interaction(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("interaction_create", _interaction)

    # botpy.flags.Intents.message_audit
    def parse_message_audit_pass(self, payload):
        _message_audit = MessageAudit(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("message_audit_pass", _message_audit)

    def parse_message_audit_reject(self, payload):
        _message_audit = MessageAudit(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("message_audit_reject", _message_audit)

    # botpy.flags.Intents.audio_action
    def parse_audio_start(self, payload):
        _audio = Audio(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("audio_start", _audio)

    def parse_audio_finish(self, payload):
        _audio = Audio(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("audio_finish", _audio)

    def parse_on_mic(self, payload):
        _audio = Audio(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("on_mic", _audio)

    def parse_off_mic(self, payload):
        _audio = Audio(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("off_mic", _audio)

    # botpy.flags.Intents.public_guild_messages
    def parse_at_message_create(self, payload):
        _message = Message(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("at_message_create", _message)

    def parse_public_message_delete(self, payload):
        _message = Message(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("public_message_delete", _message)

    # botpy.flags.Intents.public_messages
    def parse_group_at_message_create(self, payload):
        _message = GroupMessage(self.api, payload.get("id", None), payload.get("d", {}))
        self._dispatch("group_at_message_create", _message)

    def parse_c2c_message_create(self, payload):
        _message = C2CMessage(self.api, payload.get("id", None), payload.get("d", {}))
        self._dispatch("c2c_message_create", _message)

    def parse_group_add_robot(self, payload):
        _event = GroupManageEvent(self.api, payload.get("id", None), payload.get("d", {}))
        self._dispatch("group_add_robot", _event)

    def parse_group_del_robot(self, payload):
        _event = GroupManageEvent(self.api, payload.get("id", None), payload.get("d", {}))
        self._dispatch("group_del_robot", _event)

    def parse_group_msg_reject(self, payload):
        _event = GroupManageEvent(self.api, payload.get("id", None), payload.get("d", {}))
        self._dispatch("group_msg_reject", _event)

    def parse_group_msg_receive(self, payload):
        _event = GroupManageEvent(self.api, payload.get("id", None), payload.get("d", {}))
        self._dispatch("group_msg_receive", _event)

    def parse_friend_add(self, payload):
        _event = C2CManageEvent(self.api, payload.get("id", None), payload.get("d", {}))
        self._dispatch("friend_add", _event)

    def parse_friend_del(self, payload):
        _event = C2CManageEvent(self.api, payload.get("id", None), payload.get("d", {}))
        self._dispatch("friend_del", _event)

    def parse_c2c_msg_reject(self, payload):
        _event = C2CManageEvent(self.api, payload.get("id", None), payload.get("d", {}))
        self._dispatch("c2c_msg_reject", _event)

    def parse_c2c_msg_receive(self, payload):
        _event = C2CManageEvent(self.api, payload.get("id", None), payload.get("d", {}))
        self._dispatch("c2c_msg_receive", _event)

    # botpy.flags.Intents.forums
    def parse_forum_thread_create(self, payload):
        _forum = Thread(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("forum_thread_create", _forum)

    def parse_forum_thread_update(self, payload):
        _forum = Thread(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("forum_thread_update", _forum)

    def parse_forum_thread_delete(self, payload):
        _forum = Thread(self.api, payload.get('id', None), payload.get('d', {}))
        self._dispatch("forum_thread_delete", _forum)

    def parse_forum_post_create(self, payload):
        self._dispatch("forum_post_create", payload.get('d', {}))

    def parse_forum_post_delete(self, payload):
        self._dispatch("forum_post_delete", payload.get('d', {}))

    def parse_forum_reply_create(self, payload):
        self._dispatch("forum_reply_create", payload.get('d', {}))

    def parse_forum_reply_delete(self, payload):
        self._dispatch("forum_reply_delete", payload.get('d', {}))

    def parse_forum_publish_audit_result(self, payload):
        self._dispatch("forum_publish_audit_result", payload.get('d', {}))

    def parse_audio_or_live_channel_member_enter(self, payload):
        _public_audio = PublicAudio(self.api, payload.get('d', {}))
        self._dispatch("audio_or_live_channel_member_enter", _public_audio)

    def parse_audio_or_live_channel_member_exit(self, payload):
        _public_audio = PublicAudio(self.api, payload.get('d', {}))
        self._dispatch("audio_or_live_channel_member_exit", _public_audio)

    def parse_open_forum_thread_create(self, payload):
        _forum = OpenThread(self.api, payload.get('d', {}))
        self._dispatch("open_forum_thread_create", _forum)

    def parse_open_forum_thread_update(self, payload):
        _forum = OpenThread(self.api, payload.get('d', {}))
        self._dispatch("open_forum_thread_update", _forum)

    def parse_open_forum_thread_delete(self, payload):
        _forum = OpenThread(self.api, payload.get('d', {}))
        self._dispatch("open_forum_thread_delete", _forum)

    def parse_open_forum_post_create(self, payload):
        _forum = OpenThread(self.api, payload.get('d', {}))
        self._dispatch("open_forum_post_create", payload.get('d', {}))

    def parse_open_forum_post_delete(self, payload):
        _forum = OpenThread(self.api, payload.get('d', {}))
        self._dispatch("open_forum_post_delete", payload.get('d', {}))

    def parse_open_forum_reply_create(self, payload):
        _forum = OpenThread(self.api, payload.get('d', {}))
        self._dispatch("open_forum_reply_create", payload.get('d', {}))

    def parse_open_forum_reply_delete(self, payload):
        _forum = OpenThread(self.api, payload.get('d', {}))
        self._dispatch("open_forum_reply_delete", payload.get('d', {}))
