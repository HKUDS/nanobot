# 云文档 (Doc)

飞书云文档 API，列出、读取、搜索云文档内容。

## API 函数

### list_files

获取云文档文件列表。

```python
from feishu_api import list_files

files = list_files(parent_node="", page_size=20)
# files -> [{name, token, type, url, ...}]
# type: "docx" / "sheet" / "bitable" / "folder" / "mindnote"
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py doc list --limit 20
python3 ${SKILL_DIR}/scripts/feishu_api.py doc list --parent-node fldcnXXX
```

### read_doc

读取云文档内容，返回 Markdown 格式纯文本。

```python
from feishu_api import read_doc

content = read_doc("doxcnXXX")  # document_id
print(content)  # Markdown 文本
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py doc read --document-id doxcnXXX
```

### search_docs

搜索云文档。

```python
from feishu_api import search_docs

items = search_docs("季度报告", page_size=10)
# items -> [{docs_token, docs_type, url, ...}]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py doc search --keyword "季度报告" --limit 10
```

## 文档类型

| token 前缀 | 类型 |
|------------|------|
| `doxcn` | 旧版文档 (doc) |
| `docx` | 新版文档 (docx) |
| `shtcn` | 电子表格 (sheet) |
| `bascn` | 多维表格 (bitable) |

## 所需权限

- `drive:drive:readonly` — 查看云空间文件
- `docx:document:readonly` — 查看文档内容
- `docs:doc:search` — 搜索文档
