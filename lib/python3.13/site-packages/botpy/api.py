# -*- coding: utf-8 -*-

# 异步api

from io import BufferedReader
from typing import Any, List, Union, BinaryIO, Dict

from .flags import Permission
from .http import BotHttp, Route
from .types import (
    guild,
    user,
    channel,
    message,
    audio,
    announce,
    permission,
    schedule,
    emoji,
    pins_message,
    reaction,
    forum,
)


class BotAPI:
    """
    机器人相关的API接口类

    使用注意:
        - 如果要直接使用api，可以通过client的内部成员变量，通过`self.api.xx`来使用
        - 设置超时时间: Client(timeout=5)
        - API当前返回的所有自定义类型数据为字典数据，通过TypedDict进行类型提示
    """

    def __init__(self, http: BotHttp):
        """
        Args:
          http (BotHttp): 用于发送请求的 http 客户端。
        """
        self._http = http

    # 频道相关接口
    async def get_guild(self, guild_id: str) -> guild.GuildPayload:
        """
        获取频道信息。

        Args:
          guild_id (str): 频道ID（一般从事件中获取相关的ID信息）

        Returns:
          GuildPayload (字典数据)
        """
        route = Route("GET", "/guilds/{guild_id}", guild_id=guild_id)
        return await self._http.request(route)

    # 频道身份组相关接口
    async def get_guild_roles(self, guild_id: str) -> guild.GuildRoles:
        """
        获取频道身份组列表

        Args:
          guild_id (str): 频道ID。

        Returns:
          GuildRolesPayload
        """
        route = Route("GET", "/guilds/{guild_id}/roles", guild_id=guild_id)
        return await self._http.request(route)

    async def create_guild_role(self, guild_id: str, **fields: Any) -> guild.GuildRole:
        """
        创建频道身份组

        Args:
          guild_id (str): 在其中创建角色的频道ID。

        Kwargs（fields）:
          name (str): 名称(非必填)
          color (int): ARGB 的 HEX 十六进制颜色值转换后的十进制数值(非必填)
          hoist (int): 在成员列表中单独展示: 0-否, 1-是(非必填)

        Returns:
          class:GuildRole
        """
        route = Route("POST", "/guilds/{guild_id}/roles", guild_id=guild_id)
        return await self._http.request(route, json=fields)

    async def update_guild_role(self, guild_id: str, role_id: str, **fields: Any) -> guild.GuildRole:
        """
        修改频道身份组

        Args:
          guild_id (str): 在其中创建角色的公会 ID。
          role_id (str): 您要修改的角色的 ID。

        Kwargs（fields）:
          name (str): 名称(非必填)
          color (int): ARGB 的 HEX 十六进制颜色值转换后的十进制数值(非必填)
          hoist (int): 在成员列表中单独展示: 0-否, 1-是(非必填)

        Returns:
          class:GuildRole
        """
        route = Route("PATCH", "/guilds/{guild_id}/roles/{role_id}", guild_id=guild_id, role_id=role_id)
        return await self._http.request(route, json=fields)

    async def delete_guild_role(self, guild_id: str, role_id: str) -> str:
        """
        删除频道身份组

        Args:
          guild_id (str): 频道 ID。
          role_id (str): 身份组 ID。

        Returns:
          成功执行返回`None`。
        """
        route = Route("DELETE", "/guilds/{guild_id}/roles/{role_id}", guild_id=guild_id, role_id=role_id)
        return await self._http.request(route)

    async def create_guild_role_member(
        self,
        guild_id: str,
        role_id: str,
        user_id: str,
        channel_id: str = None,
    ) -> str:
        """
        增加频道身份组成员。

        Args:
          guild_id (str): 频道 ID。
          role_id (str): 身份组 ID。
          user_id (str): 要添加到角色的用户的用户 ID。
          channel_id (str): 您要在其中创建角色的频道的 ID。如果要删除的身份组ID是5-子频道管理员，需要增加channel对象来指定具体是哪个子频道

        Returns:
          成功执行返回`None`。
        """
        payload = {"channel": {"id": channel_id}}

        route = Route(
            "PUT",
            "/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
            guild_id=guild_id,
            user_id=user_id,
            role_id=role_id,
        )
        return await self._http.request(route, json=payload)

    async def delete_guild_role_member(self, guild_id: str, role_id: str, user_id: str, channel_id: str = None) -> str:
        """
        删除频道身份组成员。

        Args:
          guild_id (str): 频道 ID。
          role_id (str): 身份组 ID。
          user_id (str): 用户的标识。
          channel_id (str): 您要从中删除角色的子频道的 ID。
            如果要删除的身份组ID是5-子频道管理员，需要增加channel对象来指定具体是哪个子频道

        Returns:
          成功执行返回`None`。
        """
        payload = {"channel": {"id": channel_id}}

        route = Route(
            "DELETE",
            "/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
            guild_id=guild_id,
            user_id=user_id,
            role_id=role_id,
        )
        return await self._http.request(route, json=payload)

    # 成员相关接口，添加成员到用户组等
    async def get_guild_member(self, guild_id: str, user_id: str) -> user.Member:
        """
        获取频道指定成员。

        Args:
          guild_id (str): 频道 ID。
          user_id (str): 用户 ID（一般从事件消息中获取。

        Returns:
          user.Member
        """
        route = Route(
            "GET",
            "/guilds/{guild_id}/members/{user_id}",
            guild_id=guild_id,
            user_id=user_id,
        )
        return await self._http.request(route)

    async def get_delete_member(
        self,
        guild_id: str,
        user_id: str,
        add_blacklist: bool = False,
        delete_history_msg_days: int = 0,
    ) -> str:
        """
        删除频道成员

        Args:
          guild_id (str): 频道ID
          user_id (str): 用户ID
          add_blacklist (bool): 是否同时添加黑名单
          delete_history_msg_days (int): 用于撤回该成员的消息，可以指定撤回消息的时间范围

        Returns:
          成功执行返回`None`。成功执行返回空字符串
        """
        # 注：消息撤回时间范围仅支持固定的天数：3，7，15，30。 特殊的时间范围：-1: 撤回全部消息。默认值为0不撤回任何消息。
        if delete_history_msg_days not in (3, 7, 15, 30, 0, -1):
            delete_history_msg_days = 0
        payload = {"add_blacklist": add_blacklist, "delete_history_msg_days": delete_history_msg_days}
        route = Route(
            "DELETE",
            "/guilds/{guild_id}/members/{user_id}",
            guild_id=guild_id,
            user_id=user_id,
        )
        return await self._http.request(route, json=payload)

    async def get_guild_members(self, guild_id: str, after: str = "0", limit: int = 1) -> List[user.Member]:
        """
        获取成员列表。

        注意:该接口为私域机器人权限, 需要在管理端申请权限

        Args:
          guild_id (str): 频道 ID。
          after (str): 上一批用户中最后一个用户的ID。如果这是第一个请求，请使用 0。. Defaults to 0
          limit (int): 分页大小，1-400。成员较多的频道尽量使用较大的limit值，以减少请求数。. Defaults to 1

        Returns:
          user.Member 对象的列表。
        """
        params = {"after": after, "limit": limit}

        route = Route(
            "GET",
            "/guilds/{guild_id}/members",
            guild_id=guild_id,
        )
        return await self._http.request(route, params=params)

    async def get_guild_role_members(
        self, guild_id: str, role_id: str, start_index: str = "0", limit: int = 1
    ) -> Dict[str, Union[List[user.Member], str]]:
        """
        获取频道身份组成员列表。

        注意:该接口为私域机器人权限, 需要在管理端申请权限

        Args:
          guild_id (str): 频道 ID。
          role_id (str): 身份组 ID。
          start_index (str): 将上一次回包中next填入， 如果是第一次请求填 0，默认为 0。. Defaults to 0
          limit (int): 分页大小，1-400。成员较多的频道尽量使用较大的limit值，以减少请求数。. Defaults to 1

        Returns:
          Dict[str, Union[List[user.Member], str]]
        """
        params = {"start_index": start_index, "limit": limit}

        route = Route(
            "GET",
            "/guilds/{guild_id}/roles/{role_id}/members",
            guild_id=guild_id,
            role_id=role_id,
        )
        return await self._http.request(route, params=params)

    async def get_voice_members(self, channel_id: str) -> List[user.Member]:
        """
        返回语音频道中的成员列表（暂未开放，内部测试使用）

        注意:
          公域机器人暂不支持申请，仅私域机器人可用，选择私域机器人后默认开通。
          注意: 开通后需要先将机器人从频道移除，然后重新添加，方可生效。

        Args:
          channel_id (str): 要获取其语音成员的频道的 ID。查询的子频道不是语音子频道，返回的status code为400

        Returns:
          user.Member 对象的列表。
        """
        route = Route("GET", "/channels/{channel_id}/voice/members", channel_id=channel_id)
        return await self._http.request(route)

    # 子频道相关接口
    async def get_channel(self, channel_id: str) -> channel.ChannelPayload:
        """
        获取频道信息

        Args:
          channel_id (str): 子频道 ID。

        Returns:
          channel.Channel
        """
        route = Route(
            "GET",
            "/channels/{channel_id}",
            channel_id=channel_id,
        )
        return await self._http.request(route)

    async def get_channels(self, guild_id: str) -> List[channel.ChannelPayload]:
        """
        获取频道下的子频道列表

        Args:
          guild_id (str): 频道 ID。

        Returns:
          List[channel.Channel]
        """
        route = Route(
            "GET",
            "/guilds/{guild_id}/channels",
            guild_id=guild_id,
        )
        return await self._http.request(route)

    async def create_channel(
        self, guild_id: str, name: str, type: channel.ChannelType, sub_type: channel.ChannelSubType, **fields
    ) -> channel.ChannelPayload:
        """
        创建子频道

        Args:
          guild_id (str): 频道 ID。
          name (str): 子频道名。
          type (channel.ChannelType): 子频道类型
          sub_type (channel.ChannelSubType): 子频道子类型

        Kwargs（fields）:
          position (int): 排序，非必填
          parent_id (str): 否,分组 ID
          private_type (int): 子频道私密类型 PrivateType
          private_user_ids (List[str]): 子频道私密类型成员 ID
          speak_permission (int): 子频道发言权限 SpeakPermission
          application_id (str): 应用类型子频道 AppID，仅应用子频道需要该字段

        Returns:
          通道对象。
        """
        payload = {
            "name": name,
            "type": int(type),
            "subtype": int(sub_type),
        }
        valid_keys = (
            "position",
            "parent_id",
            "private_type",
            "private_user_ids",
            "speak_permission",
            "application_id",
        )
        payload.update({k: v for k, v in fields.items() if k in valid_keys and v})
        route = Route("POST", "/guilds/{guild_id}/channels", guild_id=guild_id)
        return await self._http.request(route, json=payload)

    async def update_channel(self, channel_id: str, **fields) -> channel.ChannelPayload:
        """
        更新子频道。

        Args:
          channel_id (str): 要修改的子频道ID。

        Kwargs:
          name	            string	子频道名
          position	        int	    排序
          parent_id	        string	分组 id
          private_type	    int	    子频道私密类型 PrivateType
          speak_permission	int	    子频道发言权限 SpeakPermission

        Returns:Dict:
          channel.Channel
        """
        route = Route("PATCH", "/channels/{channel_id}", channel_id=channel_id)
        return await self._http.request(route, json=fields)

    async def delete_channel(self, channel_id: str) -> channel.ChannelPayload:
        """
        删除子频道

        Args:
          channel_id (str): 要删除的子频道 ID。

        Returns:Dict:
          删除后的channel.Channel
        """
        route = Route("DELETE", "/channels/{channel_id}", channel_id=channel_id)
        return await self._http.request(route)

    # 子频道权限相关接口
    async def get_channel_user_permissions(self, channel_id: str, user_id: str) -> channel.ChannelPermissions:
        """
        获取指定子频道用户的权限。

        Args:
          channel_id (str): 子频道 ID。
          user_id (str): 用户 ID。

        Returns:Dict
          channel.ChannelPermissions
        """
        route = Route(
            "GET", "/channels/{channel_id}/members/{user_id}/permissions", channel_id=channel_id, user_id=user_id
        )
        return await self._http.request(route)

    async def update_channel_user_permissions(
        self, channel_id: str, user_id: str, add: Permission = None, remove: Permission = None
    ) -> str:
        """
        修改指定子频道用户的权限。

        Args:
          channel_id (str): 子频道 ID。
          user_id (str): 您要更改其权限的用户的用户 ID。
          add (Permission): 添加到用户的权限。使用示例：`add = Permission(view_permission=True)`
          remove (Permission): 删除的权限类型，示例：`remove = Permission(view_permission=True,manager_permission=True)`

        Returns:
          成功执行返回`None`。
        """
        payload = {"add": str(add.value) if add else None, "remove": str(remove.value) if remove else None}

        route = Route(
            "PUT", "/channels/{channel_id}/members/{user_id}/permissions", channel_id=channel_id, user_id=user_id
        )
        return await self._http.request(route, json=payload)

    async def get_channel_role_permissions(self, channel_id: str, role_id: str) -> channel.ChannelPermissions:
        """
        获取指定子频道身份组的权限。

        Args:
          channel_id (str): 您要获取权限的子频道的 ID。
          role_id (str): 您要编辑的身份组 ID。

        Returns:Dict
          channel.ChannelPermissions 的字典数据
        """
        route = Route(
            "GET", "/channels/{channel_id}/roles/{role_id}/permissions", channel_id=channel_id, role_id=role_id
        )
        return await self._http.request(route)

    async def update_channel_role_permissions(
        self, channel_id: str, role_id: str, add: Permission = None, remove: Permission = None
    ) -> str:
        """
        修改指定子频道身份组的权限

        Args:
          channel_id (str): 您要更改权限的子频道的 ID。
          role_id (str): 要修改的身份组 ID。
          add (Permission):  添加的权限类型，示例：添加可读权限，`add = Permission(view_permission=True)`
          remove (Permission):  删除的权限类型，示例：删除可读和发言权限, `remove = Permission(view_permission=True,speak_permission=True)`

        Returns:
          成功执行返回`None`。
        """
        payload = {"add": str(add.value) if add else None, "remove": str(remove.value) if remove else None}

        route = Route(
            "PUT", "/channels/{channel_id}/roles/{role_id}/permissions", channel_id=channel_id, role_id=role_id
        )
        return await self._http.request(route, json=payload)

    # 消息
    async def get_message(self, channel_id: str, message_id: str) -> message.MessagePayload:
        """
        获取指定消息。

        Args:
          channel_id (str): 您要从中获取消息的子频道的 ID。
          message_id (str): 要删除的消息的 ID。

        Returns:
          一个消息字典对象。
        """
        route = Route(
            "GET", "/channels/{channel_id}/messages/{message_id}", channel_id=channel_id, message_id=message_id
        )
        return await self._http.request(route)

    async def post_message(
        self,
        channel_id: str,
        content: str = None,
        embed: message.Embed = None,
        ark: message.Ark = None,
        message_reference: message.Reference = None,
        image: str = None,
        file_image: Union[bytes, BinaryIO, str] = None,
        msg_id: str = None,
        event_id: str = None,
        markdown: message.MarkdownPayload = None,
        keyboard: message.Keyboard = None,
    ) -> message.Message:
        """
        发送消息。

        注意:
        - 要求操作人在该子频道具有发送消息的权限。
        - 发送成功之后，会触发一个创建消息的事件。
        - 被动回复消息有效期为 5 分钟
        - 主动推送消息每日每个子频道限 2 条
        - 发送消息接口要求机器人接口需要链接到websocket gateway 上保持在线状态

        Args:
          channel_id (str): 您要将消息发送到的子频道的 ID。
          content (str): 消息的文本内容。
          embed (message.Embed): embed 消息，一种特殊的 ark
          ark (message.Ark): ark 模版消息
          message_reference (message.Reference): 对消息的引用。
          image (str): 要发送的图像的 URL。
          file_image (bytes): 要发送的本地图像的本地路径或数据。
          msg_id (str): 您要回复的消息的 ID。您可以从 AT_CREATE_MESSAGE 事件中获取此 ID。
          event_id (str): 您要回复的消息的事件 ID。
          markdown (message.MarkdownPayload): markdown 消息
          keyboard (message.Keyboard): keyboard 消息

        Returns:
          message.Message: 一个消息字典对象。
        """
        if isinstance(file_image, BufferedReader):
            file_image = file_image.read()
        elif isinstance(file_image, str):
            with open(file_image, "rb") as img:
                file_image = img.read()
        payload = locals()
        payload.pop("self", None)
        payload.pop("img", None)
        route = Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id)
        return await self._http.request(route, json=payload)

    async def recall_message(self, channel_id: str, message_id: str, hidetip: bool = False) -> str:
        """
        撤回消息。

        注意:
          管理员可以撤回普通成员的消息
          频道主可以撤回所有人的消息

        Args:
          channel_id (str): 您要将消息发送到的频道的 ID。
          message_id (str): 要撤回的消息的 ID。
          hidetip (bool): 是否隐藏撤回提示小灰条。. Defaults to False

        Returns:
          成功执行返回`None`。
        """
        params = {"hidetip": str(hidetip).lower()}

        route = Route(
            "DELETE",
            "/channels/{channel_id}/messages/{message_id}",
            channel_id=channel_id,
            message_id=message_id,
        )
        return await self._http.request(route, params=params)

    async def post_keyboard_message(
        self,
        channel_id: str,
        keyboard: message.KeyboardPayload = None,
        markdown: message.MarkdownPayload = None,
    ) -> message.Message:
        """
        `post_keyboard_message` 使用内联键盘发送消息

        Args:
          channel_id (str): 您要将消息发送到的频道的 ID。
          keyboard (message.KeyboardPayload): keyboard 消息的构建参数
          markdown (message.MarkdownPayload): markdown 消息的构建参数。

        Returns:
          一个消息的字典数据对象。
        """
        payload = {"keyboard": keyboard, "markdown": markdown}
        route = Route(
            "POST",
            "/channels/{channel_id}/messages",
            channel_id=channel_id,
        )
        return await self._http.request(route, json=payload)

    async def on_interaction_result(self, interaction_id: str, code: int):
        """
        `on_interaction_result` 消息按钮回调结果

        Args:
          interaction_id (str): 消息按钮回调事件的 ID。
          code (int): 回调结果 0 成功，1 操作失败，2 操作频繁，3 重复操作，4 没有权限，5 仅管理员操作

        Returns:
          无
        """
        payload = {"code": code}
        route = Route(
            "PUT",
            "/interactions/{id}",
            id=interaction_id,
        )
        return await self._http.request(route, json=payload)

    async def patch_guild_message(
        self,
        channel_id: str,
        patch_msg_id: str,
        msg_id: str = None,
        event_id: str = None,
        markdown: message.MarkdownPayload = None,
        keyboard: message.KeyboardPayload = message.KeyboardPayload(content={}),
    ) -> message.Message:
        """
        修改频道markdown消息，需要先申请权限。

        Args:
          channel_id (str): 您要将消息发送到的频道的 ID。
          patch_msg_id (str): 需要修改的消息id。
          msg_id (str): 您要回复的消息的 ID。您可以从 AT_CREATE_MESSAGE 事件中获取此 ID。
          event_id (str): 您要回复的消息的事件 ID。
          markdown (message.MarkdownPayload): markdown 消息的构建参数。
          keyboard (message.KeyboardPayload): keyboard 消息的构建参数

        Returns:
          message.Message: 一个消息字典对象。
        """
        payload = locals()
        payload.pop("self", None)
        route = Route(
            "PATCH",
            "/channels/{channel_id}/messages/{patch_msg_id}",
            channel_id=channel_id,
            patch_msg_id=patch_msg_id,
        )
        return await self._http.request(route, json=payload)

    # 私信消息
    async def create_dms(self, guild_id: str, user_id: str) -> message.DmsPayload:
        """
        创建私信会话。


        Args:
          guild_id (str): 您要将私信消息的来源频道 ID。
          user_id (str): 你要发送私信的用户 ID

        Returns:
          message.DmsPayload: 一个私信会话的字典对象。
        """
        # 创建私信频道
        payload = {"recipient_id": user_id, "source_guild_id": guild_id}
        route = Route("POST", "/users/@me/dms")
        return await self._http.request(route, json=payload)

    async def post_dms(
        self,
        guild_id: str,
        content: str = None,
        embed: message.Embed = None,
        ark: message.Ark = None,
        message_reference: message.Reference = None,
        image: str = None,
        file_image: Union[bytes, BinaryIO, str] = None,
        msg_id: str = None,
        event_id: str = None,
        markdown: message.MarkdownPayload = None,
        keyboard: message.Keyboard = None,
    ) -> message.Message:
        """
        发送私信。

        注意:
        - 要求操作人在该子频道具有发送消息的权限。
        - 发送成功之后，会触发一个创建消息的事件。
        - 被动回复消息有效期为 5 分钟
        - 主动推送消息每日每个子频道限 2 条
        - 发送消息接口要求机器人接口需要链接到websocket gateway 上保持在线状态

        Args:
          guild_id (str): 您要将私信会话的 ID, 从`create_dms`的返回可以获取。
          content (str): 消息的文本内容。
          embed (message.Embed): embed 消息，一种特殊的 ark
          ark (message.Ark): ark 模版消息
          message_reference (message.Reference): 对消息的引用。
          image (str): 要发送的图像的 URL。
          file_image (bytes): 本地图片
          msg_id (str): 您要回复的消息的 ID。您可以从 AT_CREATE_MESSAGE 事件中获取此 ID。
          event_id (str): 您要回复的消息的事件 ID。
          markdown (message.MarkdownPayload): markdown 消息
          keyboard (message.Keyboard): keyboard 消息

        Returns:
          message.Message: 一个消息字典对象。
        """
        if isinstance(file_image, BufferedReader):
            file_image = file_image.read()
        elif isinstance(file_image, str):
            with open(file_image, "rb") as img:
                file_image = img.read()
        payload = locals()
        payload.pop("self", None)
        payload.pop("img", None)
        route = Route("POST", "/dms/{guild_id}/messages", guild_id=guild_id)
        return await self._http.request(route, json=payload)

    # 音频接口
    async def update_audio(self, channel_id: str, audio_control: audio.AudioControl) -> str:
        """
        音频控制

        用于控制子频道 channel_id 下的音频。
        音频接口：仅限音频类机器人才能使用，后续会根据机器人类型自动开通接口权限，现如需调用，需联系平台申请权限。

        Args:
          channel_id (str): 要将音频发布到的频道的 ID。
          audio_control (audio.AudioControl): 音频.AudioControl 字典类型数据

        Returns:
          一个字符串
        """

        payload = audio_control
        route = Route("POST", "/channels/{channel_id}/audio", channel_id=channel_id)
        return await self._http.request(route, json=payload)

    async def on_microphone(self, channel_id) -> str:
        """
        机器人在 channel_id 对应的语音子频道上麦。

        注意:
          音频接口：仅限音频类机器人才能使用，后续会根据机器人类型自动开通接口权限，现如需调用，需联系平台申请权限。

        Args:
          channel_id: 子频道 ID。

        Returns:
          成功执行返回`None`。成功执行返回空字符串
        """
        route = Route("PUT", "/channels/{channel_id}/mic", channel_id=channel_id)
        return await self._http.request(route)

    async def off_microphone(self, channel_id) -> str:
        """
        机器人在 channel_id 对应的语音子频道下麦。

        注意:
          音频接口：仅限音频类机器人才能使用，后续会根据机器人类型自动开通接口权限，现如需调用，需联系平台申请权限。

        Args:
          channel_id: 子频道 ID。

        Returns:
          成功执行返回`None`。成功执行返回空字符串
        """
        route = Route("DELETE", "/channels/{channel_id}/mic", channel_id=channel_id)
        return await self._http.request(route)

    # 用户相关接口
    async def me(self) -> user.User:
        """
        它返回当前用户的信息。

        Returns:
          一个用户对象。字典类型数据
        """
        route = Route("GET", "/users/@me")
        return await self._http.request(route)

    async def me_guilds(self, guild_id: str = None, limit: int = 100, desc: bool = False) -> List[guild.GuildPayload]:
        """
        它返回当前用户已加入的 Guild 对象列表。

        Args:
          guild_id (str): 列表的起始频道 ID。
          limit (int): 返回的最大频道数（1-100）。. Defaults to 100
          desc (bool): 如果为 True，则列表将按频道 ID 往前的数据并反序返回。. Defaults to False

        Returns:
          频道列表。
        """
        params = {"limit": limit}
        if desc and guild_id:
            params["before"] = guild_id
        elif guild_id:
            params["after"] = guild_id

        route = Route("GET", "/users/@me/guilds")
        return await self._http.request(route, params=params)

    # WebsocketAPI
    async def get_ws_url(self):
        """
        返回机器人的 websocket URL

        Returns:
          url字典数据。通过 `data['url']` 获取
        """
        route = Route("GET", "/gateway/bot")
        return await self._http.request(route)

    # 禁言接口
    async def mute_all(self, guild_id: str, mute_end_timestamp: str = None, mute_seconds: str = None) -> str:
        """
        使频道中的所有成员禁言。

        用于将频道的全体成员（非管理员）禁言。
        需要使用的 token 对应的用户具备管理员权限。如果是机器人，要求被添加为管理员。

        Args:
          guild_id (str): 要禁言的频道 ID。
          mute_end_timestamp (str): 禁言结束的时间。该值是自 1970 年 1 月 1 日 00:00:00 UTC 以来经过的毫秒数。
          mute_seconds (str): 禁言的秒数。两个字段二选一，默认以 mute_end_timestamp 为准

        Returns:
          成功执行返回`None`。
        """
        payload = {
            "mute_end_timestamp": mute_end_timestamp,
            "mute_seconds": mute_seconds,
        }
        route = Route("PATCH", "/guilds/{guild_id}/mute", guild_id=guild_id)
        return await self._http.request(route, json=payload)

    async def cancel_mute_all(self, guild_id: str) -> str:
        """
        取消频道中所有成员的禁言。

        Args:
          guild_id (str): 要取消禁言的频道 ID。

        Returns:
          成功执行返回`None`。
        """
        payload = {
            "mute_end_timestamp": "0",
            "mute_seconds": "0",
        }
        route = Route("PATCH", "/guilds/{guild_id}/mute", guild_id=guild_id)
        return await self._http.request(route, json=payload)

    async def mute_member(
        self, guild_id: str, user_id: str, mute_end_timestamp: str = None, mute_seconds: str = None
    ) -> str:
        """
        使频道中的指定成员禁言。

        用于将频道的指定成员（非管理员）禁言。
        需要使用的 token 对应的用户具备管理员权限。如果是机器人，要求被添加为管理员。

        Args:
          guild_id (str): 要禁言的频道 ID。
          user_id (str): 要禁言的成员 ID
          mute_end_timestamp (str): 禁言结束的时间。该值是自 1970 年 1 月 1 日 00:00:00 UTC 以来经过的毫秒数。
          mute_seconds (str): 禁言的秒数。两个字段二选一，默认以 mute_end_timestamp 为准

        Returns:
          成功执行返回`None`。
        """
        payload = {
            "mute_end_timestamp": mute_end_timestamp,
            "mute_seconds": mute_seconds,
        }
        route = Route("PATCH", "/guilds/{guild_id}/members/{user_id}/mute", guild_id=guild_id, user_id=user_id)
        return await self._http.request(route, json=payload)

    async def mute_multi_member(
        self, guild_id: str, user_ids: List[str], mute_end_timestamp: str = None, mute_seconds: str = None
    ) -> str:
        """
        使频道中的多个成员禁言

        Args:
          guild_id (str): 将用户禁言的频道 ID。
          user_ids (List[str]): 要禁言的用户 ID 列表。
          mute_end_timestamp (str): 禁言结束的时间。该值是自 1970 年 1 月 1 日 00:00:00 UTC 以来经过的毫秒数。
          mute_seconds (str): 将用户禁言的秒数。两个字段二选一，默认以 mute_end_timestamp 为准

        Returns:
          成功执行返回`None`。
        """
        payload = {
            "mute_end_timestamp": mute_end_timestamp,
            "mute_seconds": mute_seconds,
            "user_ids": user_ids,
        }
        route = Route("PATCH", "/guilds/{guild_id}/mute", guild_id=guild_id)
        return await self._http.request(route, json=payload)

    async def cancel_mute_multi_member(self, guild_id: str, user_ids: List[str]) -> str:
        """
        取消多个成员的禁言。

        Args:
          guild_id (str): 您想将用户禁言的频道 ID。
          user_ids (List[str]): 您要禁言的用户 ID 列表。

        Returns:
          成功执行返回`None`。
        """
        payload = {"mute_end_timestamp": "0", "mute_seconds": "0", "user_ids": user_ids}
        route = Route("PATCH", "/guilds/{guild_id}/mute", guild_id=guild_id)
        return await self._http.request(route, json=payload)

    # 公告接口
    async def create_announce(self, guild_id: str, channel_id: str, message_id: str) -> announce.Announce:
        """
        创建消息类型的频道公告。

        注意:
          推荐子频道和消息类型全局公告不能同时存在，会互相顶替设置。
          同频道内推荐子频道最多只能创建 3 条。
          只有子频道权限为全体成员可见才可设置为推荐子频道。

        Args:
          guild_id (str): 创建频道的频道ID。
          channel_id (str): 您要将通知发送到的频道的子频道 ID。
          message_id (str): 公告的消息 ID。

        Returns:
          一个新的 Announce 对象。字典类型数据
        """
        payload = {"channel_id": channel_id, "message_id": message_id}
        route = Route("POST", "/guilds/{guild_id}/announces", guild_id=guild_id)
        return await self._http.request(route, json=payload)

    async def create_recommend_announce(
        self, guild_id: str, announces_type: announce.AnnouncesType, recommend_channels: List[announce.RecommendChannel]
    ) -> announce.Announce:
        """
        创建推荐子频道类型的频道公告

        注意:
          推荐子频道和消息类型全局公告不能同时存在，会互相顶替设置。
          同频道内推荐子频道最多只能创建 3 条。
          只有子频道权限为全体成员可见才可设置为推荐子频道。

        Args:
          guild_id (str): 发公告的频道 ID
          announces_type (announce.AnnouncesType): 公告的类型。
          recommend_channels (List[announce.RecommendChannel]): 列表[announce.RecommendChannel]

        Returns:
          一个新的 Announce 对象。字典类型数据
        """
        payload = {"announces_type": int(announces_type), "recommend_channels": recommend_channels}
        route = Route("POST", "/guilds/{guild_id}/announces", guild_id=guild_id)
        return await self._http.request(route, json=payload)

    async def delete_announce(self, guild_id: str, message_id: str = "all") -> str:
        """
        删除消息类型和推荐子频道类型的频道公告。

        注意:
          message_id 有值时，会校验 message_id 合法性，若不校验校验 message_id，请将 message_id 设置为 all

        Args:
          guild_id (str): 您要从中获取公告的频道的 ID。
          message_id (str): 要删除的公告消息的 ID。

        Returns:
          成功执行返回`None`。
        """
        route = Route("DELETE", "/guilds/{guild_id}/announces/{message_id}", guild_id=guild_id, message_id=message_id)
        return await self._http.request(route)

    # 接口权限接口
    async def get_permissions(self, guild_id: str) -> List[permission.APIPermission]:
        """
        返回 bot 可以在具有给定 ID 的频道中使用的权限列表

        Args:
          guild_id (str): 获取权限的频道 ID。

        Returns:
          APIPermission 字典数据对象的列表。
        """
        route = Route("GET", "/guilds/{guild_id}/api_permission", guild_id=guild_id)
        # 多一层级
        data = await self._http.request(route)
        return data["apis"]

    async def post_permission_demand(
        self, guild_id: str, channel_id: str, api_identify: permission.APIPermissionDemandIdentify, desc: str
    ) -> permission.APIPermissionDemand:
        """
        用于创建 API 接口权限授权链接，该链接指向guild_id对应的频道

        Args:
          guild_id (str): 创建权限请求的频道ID。
          channel_id (str): 需要发送权限请求的通道的子频道ID。
          api_identify (permission.APIPermissionDemandIdentify): API 权限需求标识。
          desc (str): 权限请求的描述。

        Returns:
          一个 permission.APIPermissionDemand 字典数据对象。
        """
        payload = {"channel_id": channel_id, "api_identify": api_identify, "desc": desc}
        route = Route("POST", "/guilds/{guild_id}/api_permission/demand", guild_id=guild_id)
        return await self._http.request(route, json=payload)

    # 日程接口
    async def get_schedules(self, channel_id: str, since: str = None) -> List[schedule.Schedule]:
        """
        获取某个日程子频道里中当天的日程列表。

        注意:
          若带了参数 since，则返回结束时间在 since 之后的日程列表；若未带参数 since，则默认返回当天的日程列表。

        Args:
          channel_id (str): 您要从中获取计划的子频道的 ID。
          since (str): 这个时间后的日程列表。如果不指定此参数，则默认值为当天的日程列表。

        Returns:
          列表[schedule.Schedule]
        """
        payload = {"since": since}
        route = Route("GET", "/channels/{channel_id}/schedules", channel_id=channel_id)
        return await self._http.request(route, json=payload)

    async def get_schedule(self, channel_id: str, schedule_id: str) -> schedule.Schedule:
        """
        获取日程子频道指定的的日程的详情

        Args:
          channel_id (str): 您要从中获取计划的频道的 ID。
          schedule_id (str): 要删除的计划的 ID。
        Returns:
          schedule.Schedule 字典数据
        """
        route = Route(
            "GET", "/channels/{channel_id}/schedules/{schedule_id}", channel_id=channel_id, schedule_id=schedule_id
        )
        return await self._http.request(route)

    async def create_schedule(
        self,
        channel_id: str,
        name: str,
        start_timestamp: str,
        end_timestamp: str,
        jump_channel_id: str,
        remind_type: schedule.RemindType,
    ) -> schedule.Schedule:
        """
        用于在日程子频道创建一个日程。

        注意:
          要求操作人具有管理频道的权限，如果是机器人，则需要将机器人设置为管理员。
          创建成功后，返回创建成功的日程对象。
          创建操作频次限制

        频率限制:
          单个管理员每天限10次
          单个频道每天100次

        Args:
          channel_id (str): 创建计划的通道的 ID。
          name (str): 计划的名称。
          start_timestamp (str): 事件的开始时间，格式为 Unix 时间戳。
          end_timestamp (str): 事件的结束时间，格式为 Unix 时间戳。
          jump_channel_id (str): 要跳转到的频道的频道 ID。
          remind_type (str): 0：无提醒，1：5分钟前，2：15分钟前，3：30分钟前，4：1小时前，5：2小时前，6：1天前，7：2天前

        Returns:
          创建好的schedule.Schedule对象
        """
        payload = {
            "schedule": {
                "name": name,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "jump_channel_id": jump_channel_id,
                "reminder_id": remind_type,
            }
        }

        route = Route("POST", "/channels/{channel_id}/schedules", channel_id=channel_id)
        return await self._http.request(route, json=payload)

    async def update_schedule(
        self,
        channel_id: str,
        schedule_id: str,
        name: str,
        start_timestamp: str,
        end_timestamp: str,
        jump_channel_id: str,
        remind_type: schedule.RemindType,
    ) -> schedule.Schedule:
        """
        修改日程。

        注意:
          要求操作人具有管理频道的权限，如果是机器人，则需要将机器人设置为管理员。


        Args:
          channel_id (str): 修改日程的子频道的 ID。
          schedule_id (str): 日程ID
          name (str): 日程的名称。
          start_timestamp (str): 事件的开始时间，格式为 Unix 时间戳。
          end_timestamp (str): 事件的结束时间，格式为 Unix 时间戳。
          jump_channel_id (str): 要跳转到的频道的频道 ID。
          remind_type (str): 0：无提醒，1：5分钟前，2：15分钟前，3：30分钟前，4：1小时前，5：2小时前，6：1天前，7：2天前

        Returns:
          更新好的schedule.Schedule对象
        """
        payload = {
            "schedule": {
                "name": name,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "jump_channel_id": jump_channel_id,
                "reminder_id": remind_type,
            }
        }

        route = Route(
            "PATCH", "/channels/{channel_id}/schedules/{schedule_id}", channel_id=channel_id, schedule_id=schedule_id
        )
        return await self._http.request(route, json=payload)

    async def delete_schedule(self, channel_id: str, schedule_id: str) -> str:
        """
        删除日程

        注意:
            要求操作人具有管理频道的权限，如果是机器人，则需要将机器人设置为管理员。

        Args:
          channel_id (str): 日程所属子频道的 ID。
          schedule_id (str): 要删除的日程的 ID。

        Returns:
          成功的话回复一个字符串
        """
        route = Route(
            "DELETE", "/channels/{channel_id}/schedules/{schedule_id}", channel_id=channel_id, schedule_id=schedule_id
        )
        return await self._http.request(route)

    # 表情表态接口
    async def put_reaction(self, channel_id: str, message_id: str, emoji_type: emoji.EmojiType, emoji_id: str) -> str:
        """
        对一条消息进行表情表态。

        Args:
          channel_id (str): 消息发送的子频道的 ID。
          message_id (str): 表态的消息 ID。
          emoji_type (int): EmojiType 1: 系统表情 2: emoji表情
          emoji_id (str): 表情符号的 ID。
            参考: https://bot.q.qq.com/wiki/develop/api/openapi/emoji/model.html#emoji-%E5%88%97%E8%A1%A8

        Returns:
          成功返回空字符串。
        """
        route = Route(
            "PUT",
            "/channels/{channel_id}/messages/{message_id}/reactions/{type}/{id}",
            channel_id=channel_id,
            message_id=message_id,
            type=emoji_type,
            id=emoji_id,
        )
        return await self._http.request(route)

    async def delete_reaction(self, channel_id: str, message_id: str, emoji_type: emoji.EmojiType, emoji_id: str):
        """
        删除消息的表情表态。

        Args:
          channel_id (str): 消息发送的子频道的 ID。
          message_id (str): 表态的消息 ID。
          emoji_type (int): EmojiType 1: 系统表情 2: emoji表情
          emoji_id (str): 表情符号的 ID。
            参考: https://bot.q.qq.com/wiki/develop/api/openapi/emoji/model.html#emoji-%E5%88%97%E8%A1%A8

        Returns:
          成功返回空字符串。
        """
        route = Route(
            "DELETE",
            "/channels/{channel_id}/messages/{message_id}/reactions/{type}/{id}",
            channel_id=channel_id,
            message_id=message_id,
            type=emoji_type,
            id=emoji_id,
        )
        return await self._http.request(route)

    async def get_reaction_users(
        self,
        channel_id: str,
        message_id: str,
        emoji_type: emoji.EmojiType,
        emoji_id: str,
        cookie: str = None,
        limit: int = 20,
    ) -> reaction.ReactionUsers:
        """
        获取表情表态用户列表

        Args:
          channel_id (str): 消息所在子频道的 ID。
          message_id (str): 要从中获取表情表态的消息的 ID。
          emoji_type (emoji.EmojiType): 表情符号的类型。1: 系统表情, 2: emoji表情
          emoji_id (str): 表情符号的 ID。
          cookie (str): cookie 上次请求返回的cookie，第一次请求无需填写。
          limit (int): 返回的最大用户数 (1-100)。. Defaults to 20

        Returns:
          对带有特定表情符号的消息做出反应的用户列表。
        """
        route = Route(
            "GET",
            "/channels/{channel_id}/messages/{message_id}/reactions/{type}/{id}",
            channel_id=channel_id,
            message_id=message_id,
            type=emoji_type,
            id=emoji_id,
        )
        params = {"limit": limit, "cookie": cookie} if cookie else {"limit": limit}
        return await self._http.request(route, params=params)

    # 精华消息API
    async def put_pin(self, channel_id: str, message_id: str) -> pins_message.PinsMessage:
        """
        在子频道内添加精华消息。

        注意:
          每个子频道最多20条精华消息
          只有可见的消息才能被设置为精华消息
          返回对象中 message_ids 为当前请求后子频道内所有精华消息数组

        Args:
          channel_id (str): 用于固定消息的子频道 ID。
          message_id (str): 要固定的消息的 ID。

        Returns:
          频道中所有固定消息的列表。
        """
        route = Route(
            "PUT",
            "/channels/{channel_id}/pins/{message_id}",
            channel_id=channel_id,
            message_id=message_id,
        )
        return await self._http.request(route, json={})

    async def delete_pin(self, channel_id: str, message_id: str):
        """
        删除精华消息。

        注意:
          用于删除子频道 channel_id 下指定 message_id 的精华消息。
          删除子频道内全部精华消息，请将 message_id 设置为 all

        Args:
          channel_id (str): 用于固定消息的子频道 ID。
          message_id (str): 要固定的消息的 ID。

        Returns:
          成功返回空字符串。
        """
        route = Route(
            "DELETE",
            "/channels/{channel_id}/pins/{message_id}",
            channel_id=channel_id,
            message_id=message_id,
        )
        return await self._http.request(route)

    async def get_pins(self, channel_id: str) -> pins_message.PinsMessage:
        """
        用于获取子频道内的所有精华消息。

        Args:
          channel_id (str): 需要获取精华消息的子频道 ID

        Returns:
          频道中的精华消息。pins_message.PinsMessage 字典数据
        """
        route = Route(
            "GET",
            "/channels/{channel_id}/pins",
            channel_id=channel_id,
        )
        return await self._http.request(route)

    # 帖子相关接口
    async def get_threads(self, channel_id: str) -> forum.ForumRsp:
        """
        该接口用于获取子频道下的帖子列表。

        Args:
          channel_id (str): 要获取其帖子列表的子频道的 ID。

        Returns:
          返回值是一个 ForumRsp 对象。
        """
        route = Route(
            "GET",
            "/channels/{channel_id}/threads",
            channel_id=channel_id,
        )
        return await self._http.request(route)

    async def get_thread_detail(self, channel_id: str, thread_id: str) -> forum.ThreadInfo:
        """
        该接口用于获取子频道下的帖子详情。

        Args:
          channel_id (str): 子频道的 ID。
          thread_id (str): 要查询的帖子的 ID。

        Returns:
          返回值是一个ThreadInfo 对象。
        """
        route = Route(
            "GET",
            "/channels/{channel_id}/threads/{thread_id}",
            channel_id=channel_id,
            thread_id=thread_id,
        )
        return await self._http.request(route)

    async def post_thread(self, channel_id: str, title: str, content: str, format: forum.Format) -> forum.PostThreadRsp:
        """
        该接口用于发表帖子。

        Args:
          channel_id (str): 子频道 ID。
          title (str): 线程的标题。
          content (str): 帖子的内容。
          format (forum.Format): 内容的格式。

        Returns:
          返回PostThreadRsp 对象。
        """
        route = Route(
            "PUT",
            "/channels/{channel_id}/threads",
            channel_id=channel_id,
        )

        payload = {"title": title, "content": content, "format": format}
        return await self._http.request(route, json=payload)

    async def delete_thread(self, channel_id: str, thread_id: str) -> str:
        """
        `该接口用于删除指定子频道下的某个帖子

        Args:
          channel_id (str): 要从中删除帖子的子频道的 ID。
          thread_id (str): 要删除的帖子的 ID。

        Returns:
          成功返回空字符串。
        """
        route = Route(
            "DELETE", "/channels/{channel_id}/threads/{thread_id}", channel_id=channel_id, thread_id=thread_id
        )
        return await self._http.request(route)

    async def post_group_message(
        self,
        group_openid: str,
        msg_type: int = 0,
        content: str = None,
        embed: message.Embed = None,
        ark: message.Ark = None,
        message_reference: message.Reference = None,
        media: message.Media = None,
        msg_id: str = None,
        msg_seq: int = 1,
        event_id: str = None,
        markdown: message.MarkdownPayload = None,
        keyboard: message.Keyboard = None,
    ) -> message.Message:
        """
        发送消息。

        注意:
        - 要求操作人在该群具有发送消息的权限。
        - 发送成功之后，会触发一个创建消息的事件。
        - 被动回复消息有效期为 5 分钟
        - 发送消息接口要求机器人接口需要链接到websocket gateway 上保持在线状态

        Args:
          group_openid (str): 您要将消息发送到的群的 ID。
          msg_type (int): 消息类型：0 是文本，1 图文混排，2 是 markdown，3 ark，4 embed，7 media 富媒体
          content (str): 消息的文本内容。
          embed (message.Embed): embed 消息，一种特殊的 ark
          ark (message.Ark): ark 模版消息
          message_reference (message.Reference): 对消息的引用。
          media (message.Media): 富媒体消息
          msg_id (str): 您要回复的消息的 ID。
          msg_seq (int): 回复消息的序号，与 msg_id 联合使用，默认是1。相同的 msg_id + msg_seq 重复发送会失败。
          event_id (str): 您要回复的消息的事件 ID。
          markdown (message.MarkdownPayload): markdown 消息
          keyboard (message.Keyboard): keyboard 消息

        Returns:
          message.Message: 一个消息字典对象。
        """
        payload = locals()
        payload.pop("self", None)
        route = Route("POST", "/v2/groups/{group_openid}/messages", group_openid=group_openid)
        return await self._http.request(route, json=payload)

    async def post_c2c_message(
        self,
        openid: str,
        msg_type: int = 0,
        content: str = None,
        embed: message.Embed = None,
        ark: message.Ark = None,
        message_reference: message.Reference = None,
        media: message.Media = None,
        msg_id: str = None,
        msg_seq: str = 1,
        event_id: str = None,
        markdown: message.MarkdownPayload = None,
        keyboard: message.Keyboard = None,
    ) -> message.Message:
        """
        发送消息。

        注意:
        - 要求操作人具有发送消息的权限。
        - 发送成功之后，会触发一个创建消息的事件。
        - 被动回复消息有效期为 5 分钟
        - 发送消息接口要求机器人接口需要链接到websocket gateway 上保持在线状态

        Args:
          openid (str): 您要将消息发送到的用户的 ID。
          msg_type (int): 消息类型：0 是文本，1 图文混排，2 是 markdown，3 ark，4 embed，7 media 富媒体
          content (str): 消息的文本内容。
          embed (message.Embed): embed 消息，一种特殊的 ark
          ark (message.Ark): ark 模版消息
          message_reference (message.Reference): 对消息的引用。
          media (message.Media): 富媒体消息
          msg_id (str): 您要回复的消息的 ID。
          msg_seq (int): 回复消息的序号，与 msg_id 联合使用，默认是1。相同的 msg_id + msg_seq 重复发送会失败。
          event_id (str): 您要回复的消息的事件 ID。
          markdown (message.MarkdownPayload): markdown 消息
          keyboard (message.Keyboard): keyboard 消息

        Returns:
          message.Message: 一个消息字典对象。
        """
        payload = locals()
        payload.pop("self", None)
        route = Route("POST", "/v2/users/{openid}/messages", openid=openid)
        return await self._http.request(route, json=payload)

    async def post_group_file(
        self,
        group_openid: str,
        file_type: int,
        url: str,
        srv_send_msg: bool = False,
    ) -> message.Media:
        """
        上传/发送群聊图片

        Args:
          group_openid (str): 您要将消息发送到的群的 ID
          file_type (int): 媒体类型：1 图片png/jpg，2 视频mp4，3 语音silk，4 文件（暂不开放）
          url (str): 需要发送媒体资源的url
          srv_send_msg (bool): 设置 true 会直接发送消息到目标端，且会占用主动消息频次
        """
        payload = locals()
        payload.pop("self", None)
        route = Route("POST", "/v2/groups/{group_openid}/files", group_openid=group_openid)
        return await self._http.request(route, json=payload)

    async def post_c2c_file(
        self,
        openid: str,
        file_type: int,
        url: str,
        srv_send_msg: bool = False,
    ) -> message.Media:
        """
        上传/发送c2c图片

        Args:
          openid (str): 您要将消息发送到的用户的 ID
          file_type (int): 媒体类型：1 图片png/jpg，2 视频mp4，3 语音silk，4 文件（暂不开放）
          url (str): 需要发送媒体资源的url
          srv_send_msg (bool): 设置 true 会直接发送消息到目标端，且会占用主动消息频次
        """
        payload = locals()
        payload.pop("self", None)
        route = Route("POST", "/v2/users/{openid}/files", openid=openid)
        return await self._http.request(route, json=payload)
