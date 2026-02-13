# 飞书机器人文件传输功能问题分析报告

## 问题概述

飞书机器人无法使用文件传输功能，通过飞书机器人发送的文档、图片等文件无法被分析和处理。

**状态：✅ 已修复**

## 根本原因分析

### 1. 当前实现的问题

在 [`nanobot/channels/feishu.py`](nanobot/channels/feishu.py:282-288) 中，当接收到非文本消息时，代码只是简单地返回一个占位符字符串：

```python
# Parse message content
if msg_type == "text":
    try:
        content = json.loads(message.content).get("text", "")
    except json.JSONDecodeError:
        content = message.content or ""
else:
    content = MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]")  # 只是返回占位符
```

**问题**：
- 没有实际下载文件内容
- 没有将文件信息传递给消息总线
- 只是简单地用 `[image]`、`[file]` 等占位符替换

### 2. 对比其他Channel的实现

#### Telegram Channel（正确实现）
在 [`nanobot/channels/telegram.py`](nanobot/channels/telegram.py:291-340) 中：

```python
# Handle media files
media_file = None
media_type = None

if message.photo:
    media_file = message.photo[-1]  # Largest photo
    media_type = "image"
elif message.voice:
    media_file = message.voice
    media_type = "voice"
elif message.audio:
    media_file = message.audio
    media_type = "audio"
elif message.document:
    media_file = message.document
    media_type = "file"

# Download media if present
if media_file and self._app:
    try:
        file = await self._app.bot.get_file(media_file.file_id)
        ext = self._get_extension(media_type, getattr(media_file, 'mime_type', None))
        
        # Save to workspace/media/
        from pathlib import Path
        media_dir = Path.home() / ".nanobot" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
        await file.download_to_drive(str(file_path))
        
        media_paths.append(str(file_path))
        # ... 处理语音转录等
```

**关键点**：
1. 检测消息类型（photo, voice, audio, document）
2. 使用平台API获取文件
3. 下载到本地目录
4. 将文件路径传递给 `_handle_message` 的 `media` 参数

#### Discord Channel（正确实现）
在 [`nanobot/channels/discord.py`](nanobot/channels/discord.py:200-223) 中也有类似的附件下载逻辑。

### 3. BaseChannel接口支持

[`nanobot/channels/base.py`](nanobot/channels/base.py:86-122) 中的 `_handle_message` 方法已经支持 `media` 参数：

```python
async def _handle_message(
    self,
    sender_id: str,
    chat_id: str,
    content: str,
    media: list[str] | None = None,  # 支持媒体文件路径
    metadata: dict[str, Any] | None = None
) -> None:
    # ...
    msg = InboundMessage(
        channel=self.name,
        sender_id=str(sender_id),
        chat_id=str(chat_id),
        content=content,
        media=media or [],  # 传递媒体文件
        metadata=metadata or {}
    )
```

### 4. 飞书API能力

飞书开放平台提供了文件下载API：
- 消息内容中包含 `file_key` 字段
- 需要调用 `im.message.resource.get` API 下载文件
- 支持图片、文档、音频等多种文件类型

## 具体问题点

### 问题1：缺少文件下载逻辑
飞书channel没有实现文件下载功能，只是简单地用占位符替换非文本消息。

### 问题2：没有传递media参数
在调用 `_handle_message` 时（第295-304行），没有传递 `media` 参数：

```python
await self._handle_message(
    sender_id=sender_id,
    chat_id=reply_to,
    content=content,
    metadata={
        "message_id": message_id,
        "chat_type": chat_type,
        "msg_type": msg_type,
    }
    # 缺少 media=media_paths
)
```

### 问题3：没有解析文件信息
飞书消息的 `content` 字段中包含文件的 `file_key`，但当前代码没有解析这个信息。

## 解决方案

### 方案概述

需要修改 [`nanobot/channels/feishu.py`](nanobot/channels/feishu.py) 的 `_on_message` 方法，添加文件下载逻辑：

1. **解析消息内容**：提取 `file_key` 和文件类型
2. **下载文件**：使用飞书API下载文件到本地
3. **传递文件路径**：将下载的文件路径通过 `media` 参数传递给消息总线
4. **处理特殊类型**：如语音转录等

### 需要添加的功能

1. **文件下载方法**：
   ```python
   async def _download_file(self, file_key: str, msg_type: str) -> str | None:
       """Download file from Feishu using file_key."""
       # 使用飞书API下载文件
       # 保存到 ~/.nanobot/media/ 目录
       # 返回本地文件路径
   ```

2. **消息类型处理**：
   - `image`：下载图片文件
   - `file`：下载文档文件
   - `audio`：下载音频文件（可选：语音转录）
   - `video`：下载视频文件

3. **修改_on_message方法**：
   - 解析消息内容获取 `file_key`
   - 调用下载方法
   - 将文件路径添加到 `media_paths` 列表
   - 传递给 `_handle_message`

### 飞书API调用示例

```python
from lark_oapi.api.im.v1 import GetMessageResourceRequest

async def _download_file(self, file_key: str, msg_type: str) -> str | None:
    """Download file from Feishu."""
    try:
        request = GetMessageResourceRequest.builder() \
            .message_id(self._message_id) \
            .file_key(file_key) \
            .type(msg_type) \
            .build()
        
        response = self._client.im.v1.message_resource.get(request)
        
        if response.success():
            # 保存文件到本地
            from pathlib import Path
            media_dir = Path.home() / ".nanobot" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            
            ext = self._get_extension(msg_type, response.mime_type)
            file_path = media_dir / f"{file_key[:16]}{ext}"
            
            with open(file_path, 'wb') as f:
                f.write(response.file)
            
            return str(file_path)
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
    return None
```

## 影响范围

### 当前影响
- 用户无法通过飞书机器人发送图片进行分析
- 用户无法通过飞书机器人发送文档进行处理
- 语音消息无法被转录
- 所有非文本消息都被简单地替换为占位符

### 修复后的效果
- 支持图片分析和处理
- 支持文档内容提取和分析
- 支持语音转录（需要配置转录服务）
- 与Telegram、Discord等channel功能对齐

## 总结

飞书机器人无法使用文件传输功能的核心原因是：
1. **缺少文件下载逻辑**：没有实现从飞书API下载文件的功能
2. **没有传递media参数**：即使下载了文件，也没有传递给消息总线
3. **只处理文本消息**：对非文本消息只是简单地用占位符替换
4. **文件路径权限问题**：文件下载到 `~/.nanobot/media/`，当 `restrict_to_workspace: true` 时AI无法访问

## 已实施的修复

### 1. 添加文件下载功能
- 在 [`nanobot/channels/feishu.py`](nanobot/channels/feishu.py) 中添加了 `_download_file` 方法
- 使用飞书 `im.message.resource.get` API下载文件
- 支持图片、文档、音频、视频等多种文件类型

### 2. 修复权限问题
- 修改文件下载路径从 `~/.nanobot/media/` 到 `{workspace}/media/`
- 在 `FeishuChannel.__init__` 中添加 `workspace` 参数
- 在 `ChannelManager` 初始化时传递 `workspace_path`
- 确保即使 `restrict_to_workspace: true`，AI也能访问下载的文件

### 3. 增强媒体处理
- 修改 [`nanobot/agent/context.py`](nanobot/agent/context.py) 的 `_build_user_content` 方法
- 图片文件：转换为base64编码，直接传递给LLM进行视觉分析
- 非图片文件：在消息中添加文件路径引用，AI可以使用 `read_file` 工具读取

### 4. 完善消息处理
- 修改 `_on_message` 方法，解析消息内容获取 `file_key`
- 下载文件并传递给消息总线的 `media` 参数
- 支持多种文件类型的扩展名识别

## 修复后的效果

现在飞书机器人可以：
- ✅ 接收并下载用户发送的图片
- ✅ 接收并下载用户发送的文档
- ✅ 接收并下载用户发送的音频/视频
- ✅ 将文件路径传递给AI代理进行分析处理
- ✅ 图片文件会被转换为base64，LLM可以直接进行视觉分析
- ✅ 文档文件会在消息中提供路径，AI可以使用 `read_file` 工具读取
- ✅ 与Telegram、Discord等channel功能对齐
- ✅ 支持 `restrict_to_workspace: true` 配置

## 文件下载位置

文件会被下载到工作空间的 `media/` 目录：
- 默认路径：`~/.nanobot/workspace/media/`
- 自定义路径：根据配置的 `workspace` 路径

这样确保了AI代理即使在工作空间限制模式下也能访问这些文件。
