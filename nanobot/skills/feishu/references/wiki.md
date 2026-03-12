# 知识库 (Wiki)

飞书知识库 API，管理知识空间、节点和内容搜索。

## API 函数

### wiki_list_spaces

获取知识空间列表。

```python
from feishu_api import wiki_list_spaces

data = wiki_list_spaces(page_size=50)
# data["items"] -> [{space_id, name, description, visibility, ...}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py wiki spaces
```

### wiki_get_space

获取知识空间详情。

```python
from feishu_api import wiki_get_space

data = wiki_get_space("space_id_xxx")
# data["space"] -> {space_id, name, description, ...}
```

### wiki_list_nodes

获取知识空间节点列表。

```python
from feishu_api import wiki_list_nodes

data = wiki_list_nodes(
    space_id="space_id_xxx",
    parent_node_token="",        # 空字符串获取根节点
    page_size=50,
)
# data["items"] -> [{node_token, obj_token, obj_type, title, has_child, ...}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py wiki nodes --space-id xxx
python3 ${SKILL_DIR}/scripts/feishu_api.py wiki nodes --space-id xxx --parent-node wikcnXXX
```

### wiki_get_node

获取节点信息。

```python
from feishu_api import wiki_get_node

data = wiki_get_node("space_id_xxx", "node_token_xxx")
# data["node"] -> {node_token, obj_token, obj_type, title, ...}
```

### wiki_create_node

创建知识库节点（或将已有文档移入知识库）。

```python
from feishu_api import wiki_create_node

# 创建新节点
data = wiki_create_node("space_id", "docx", parent_node_token="wikcnXXX", title="新文档")

# 移入已有文档
data = wiki_create_node("space_id", "docx", obj_token="doxcnXXX")
```

### wiki_search

搜索知识库内容。

```python
from feishu_api import wiki_search

data = wiki_search("开发规范", space_id="space_id_xxx")
# data["items"] -> [{title, node_token, space_id, ...}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py wiki search --keyword "开发规范"
python3 ${SKILL_DIR}/scripts/feishu_api.py wiki search --keyword "开发规范" --space-id xxx
```

## obj_type 对象类型

| 值 | 说明 |
|----|------|
| doc | 旧版文档 |
| docx | 新版文档 |
| sheet | 电子表格 |
| bitable | 多维表格 |
| mindnote | 思维导图 |
| file | 文件 |

## 所需权限

- `wiki:wiki:readonly` — 查看知识库
- `wiki:wiki` — 知识库完整权限
