# 百科 (Baike)

飞书百科 API，搜索和管理企业百科词条。

## API 函数

### baike_search

搜索百科词条。

```python
from feishu_api import baike_search

data = baike_search("OKR", page_size=20)
# data["entities"] -> [{id, main_keys, description, ...}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py baike search --query "OKR" --limit 20
```

### baike_get_entity

获取词条详情。

```python
from feishu_api import baike_get_entity

data = baike_get_entity("entity_id_xxx")
# data["entity"] -> {id, main_keys, aliases, description, related_meta, ...}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py baike get --entity-id xxx
```

### baike_create_entity

创建百科词条。

```python
from feishu_api import baike_create_entity

data = baike_create_entity(
    main_keys=["OKR"],
    description="Objectives and Key Results，目标与关键结果工作法。",
    aliases=["目标管理"],
)
# data["entity"] -> {id, ...}
```

### baike_update_entity

更新百科词条。

```python
from feishu_api import baike_update_entity

baike_update_entity("entity_id_xxx", {"description": "更新后的描述"})
```

### baike_highlight

词条高亮 — 在文本中标记匹配的百科词条。

```python
from feishu_api import baike_highlight

data = baike_highlight("我们团队使用OKR进行目标管理")
# data["phrases"] -> [{name, entity_ids}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py baike highlight --text "我们团队使用OKR进行目标管理"
```

## 所需权限

- `baike:entity:readonly` — 查看百科词条
- `baike:entity` — 百科完整权限
