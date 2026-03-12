# 消息收发 (Message)

飞书消息 API，支持发送、回复、获取单条消息和会话历史。

## API 函数

### send_message

发送消息（通用）。

```python
from feishu_api import send_message
import json

data = send_message(
    receive_id="oc_xxx",           # 接收方 ID
    msg_type="text",               # text / post / interactive / image / ...
    content=json.dumps({"text": "Hello"}),  # JSON 字符串
    receive_id_type="chat_id",     # chat_id / open_id / union_id / email
)
# data -> {message_id, ...}
```

### send_text

发送文本消息（便捷函数）。

```python
from feishu_api import send_text

data = send_text("oc_xxx", "你好！", receive_id_type="chat_id")
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py message send --receive-id oc_xxx --text "你好" --id-type chat_id
```

### reply_message

回复已有消息。

```python
from feishu_api import reply_message
import json

data = reply_message("om_xxx", "text", json.dumps({"text": "收到"}))
```

### get_message

获取单条消息详情。

```python
from feishu_api import get_message

data = get_message("om_xxx")
# data["items"][0] -> {message_id, msg_type, body, sender, ...}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py message get --message-id om_xxx
```

### get_chat_history

获取会话历史消息。

```python
from feishu_api import get_chat_history

data = get_chat_history(
    chat_id="oc_xxx",
    start_time="1710000000",       # 秒级时间戳（可选）
    end_time="1710086400",         # 秒级时间戳（可选）
    page_size=20,
)
# data["items"] -> [{message_id, msg_type, body, sender, create_time, ...}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py message history --chat-id oc_xxx --limit 20
```

## 消息类型 msg_type

| 类型 | content 格式 |
|------|-------------|
| text | `{"text": "内容"}` |
| post | `{"zh_cn": {"title": "标题", "content": [[{"tag": "text", "text": "段落"}]]}}` |
| interactive | 卡片 JSON |
| image | `{"image_key": "img_xxx"}` |

## 所需权限

- `im:message:send_as_bot` — 发送消息
- `im:message:readonly` — 获取消息
- `im:message` — 完整消息权限
