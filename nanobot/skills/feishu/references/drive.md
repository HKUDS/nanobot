# 云空间 / 文件管理 (Drive)

飞书云空间 API，管理文件夹、上传下载文件和文档权限。

## API 函数

### drive_create_folder

创建文件夹。

```python
from feishu_api import drive_create_folder

data = drive_create_folder("新文件夹", folder_token="fldcnXXX")
# data -> {token, url}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py drive mkdir --name "新文件夹" --folder-token fldcnXXX
```

### drive_upload_file

上传文件到云空间（< 20MB 文件使用 upload_all）。

```python
from feishu_api import drive_upload_file

data = drive_upload_file("/path/to/file.pdf", parent_node="fldcnXXX")
# data -> {file_token}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py drive upload --file /path/to/file.pdf --parent-node fldcnXXX
```

### drive_download_file

下载文件。

```python
from feishu_api import drive_download_file

path = drive_download_file("boxcnXXX", "/tmp/output.pdf")
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py drive download --file-token boxcnXXX --save-path /tmp/output.pdf
```

### drive_move_file

移动文件。

```python
from feishu_api import drive_move_file

drive_move_file("boxcnXXX", dst_folder_token="fldcnYYY")
```

### drive_copy_file

复制文件。

```python
from feishu_api import drive_copy_file

data = drive_copy_file("boxcnXXX", dst_folder_token="fldcnYYY", name="副本")
```

### drive_delete_file

删除文件。

```python
from feishu_api import drive_delete_file

drive_delete_file("boxcnXXX")
```

### drive_add_permission

添加文档权限。

```python
from feishu_api import drive_add_permission

drive_add_permission(
    token="doxcnXXX",
    member_type="user",          # user / chat / department
    member_id="ou_xxx",
    perm="view",                 # view / edit / full_access
    token_type="docx",           # doc / sheet / bitable / folder / docx
)
```

## 所需权限

- `drive:drive` — 云空间完整权限
- `drive:drive:readonly` — 只读权限
- `drive:file:upload` — 上传文件
- `drive:file:download` — 下载文件
