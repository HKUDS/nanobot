# 通讯录 (Contact)

飞书通讯录 API，查询用户信息和部门组织结构。

## API 函数

### get_user

获取用户信息。

```python
from feishu_api import get_user

data = get_user("ou_xxx", user_id_type="open_id")
user = data["user"]
# user -> {open_id, name, en_name, email, mobile, avatar, department_ids, employee_id, ...}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py contact user --user-id ou_xxx --id-type open_id
```

### list_department_users

获取部门下用户列表。

```python
from feishu_api import list_department_users

data = list_department_users(
    department_id="0",                   # "0" 表示根部门
    page_size=50,
    department_id_type="open_department_id",
    user_id_type="open_id",
)
# data["items"] -> [{open_id, name, department_ids, ...}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py contact dept-users --department-id 0 --limit 50
```

### get_department

获取部门信息。

```python
from feishu_api import get_department

data = get_department("od_xxx", department_id_type="open_department_id")
# data["department"] -> {name, department_id, open_department_id, parent_department_id, ...}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py contact dept --department-id od_xxx
```

### list_departments

获取子部门列表。

```python
from feishu_api import list_departments

data = list_departments(parent_department_id="0", page_size=50)
# data["items"] -> [{department_id, name, ...}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py contact dept-children --parent-id 0 --limit 50
```

## 所需权限

- `contact:user.base:readonly` — 获取用户基本信息
- `contact:user.employee_id:readonly` — 获取员工工号
- `contact:user.email:readonly` — 获取用户邮箱
- `contact:user.phone:readonly` — 获取用户手机号
- `contact:department.base:readonly` — 获取部门基本信息

**重要**：还需要在「飞书管理后台 → 安全设置 → 数据权限」中将「通讯录权限范围」设置为「全部成员」，否则只能获取到机器人所在群的成员。
