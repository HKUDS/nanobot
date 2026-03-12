# 群组管理 (Chat)

飞书 IM 群组相关 API，管理机器人所在的群、获取群信息和群成员。

## API 函数

### list_chats

获取机器人所在的群列表。

```python
from feishu_api import list_chats

data = list_chats(page_size=20, page_token="")
# data["items"] -> [{chat_id, name, description, owner_id, ...}]
# data["has_more"] -> bool
# data["page_token"] -> str
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py chat list --limit 20
```

### get_chat

获取群详细信息。

```python
from feishu_api import get_chat

info = get_chat("oc_xxx")
# info -> {chat_id, name, description, owner_id, chat_mode, chat_type, ...}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py chat info --chat-id oc_xxx
```

### get_chat_members

获取群成员列表（单页）。

```python
from feishu_api import get_chat_members

data = get_chat_members("oc_xxx", member_id_type="open_id", page_size=100)
# data["items"] -> [{member_id, name, tenant_key}]
# data["has_more"] -> bool
```

### get_chat_members_all

获取群全部成员（自动分页）。

```python
from feishu_api import get_chat_members_all

members = get_chat_members_all("oc_xxx")
# members -> [{member_id, name, tenant_key}, ...]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py chat members --chat-id oc_xxx --all
python3 ${SKILL_DIR}/scripts/feishu_api.py chat members --chat-id oc_xxx --limit 50
```

## 所需权限

- `im:chat:readonly` — 获取群组信息
- `im:chat.member:read` — 获取群成员
