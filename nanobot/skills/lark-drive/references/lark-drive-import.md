# drive +import

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

将本地文件（如 Word、TXT、Markdown、Excel 等）导入并转换为飞书在线云文档（docx、sheet、bitable）。底层统一通过 `POST /open-apis/drive/v1/import_tasks` 接口创建导入任务，并在 shortcut 内做有限次数轮询 `GET /open-apis/drive/v1/import_tasks/:ticket`。

> [!IMPORTANT]
> 当用户说“把本地 Excel / CSV 导入成 Base / 多维表格 / bitable 文档”时，第一步必须使用 `drive +import --type bitable`。
> 这是 Drive 导入场景，不是 `lark-base` 的建表 / 写记录场景。
> 只有导入完成并拿到新文档的 `token` / `url` 后，后续字段、记录、视图等表内操作才切换到 `lark-cli base +...`。

## 命令

```bash
# 导入 Markdown 为新版文档 (docx)
lark-cli drive +import --file ./README.md --type docx

# 导入 Excel 为电子表格 (sheet)
lark-cli drive +import --file ./data.xlsx --type sheet

# 导入 Excel 为多维表格 / Base (bitable)
lark-cli drive +import --file ./crm.xlsx --type bitable --name "客户台账"

# 导入到指定文件夹，并指定导入后的文件名
lark-cli drive +import --file ./data.csv --type bitable --folder-token <FOLDER_TOKEN> --name "导入数据表"

# 预览底层调用链（上传 -> 创建任务 -> 轮询）
lark-cli drive +import --file ./README.md --type docx --dry-run
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--file` | 是 | 本地文件路径，根据文件后缀名自动推断 `file_extension`；文件需满足对应格式的导入大小限制，超过 20MB 且仍在允许范围内时会自动切换分片上传 |
| `--type` | 是 | 导入目标云文档格式。可选值：`docx` (新版文档)、`sheet` (电子表格)、`bitable` (多维表格) |
| `--folder-token` | 否 | 目标文件夹 token，不传则请求中的 `point.mount_key` 为空字符串，Import API 会将其解释为导入到云空间根目录 |
| `--name` | 否 | 导入后的在线云文档名称，不传默认使用本地文件名去掉扩展名后的结果 |

## 行为说明

- **完整执行流程**：此 shortcut 内部封装了完整流程：
  1. 自动上传源文件获取 `file_token`：
     - 20MB 及以下：调用素材上传接口 `POST /open-apis/drive/v1/medias/upload_all`
     - 超过 20MB：自动切换为分片上传 `upload_prepare -> upload_part -> upload_finish`
  2. 调用 `import_tasks` 接口发起导入任务，自动根据本地文件提取扩展名并构造挂载点（`mount_point`）参数
  3. 自动轮询查询导入任务状态；如果在内置轮询窗口内完成，则直接返回导入结果；如果仍未完成，则返回 `ticket`、当前状态和后续查询命令
- **默认根目录行为**：不传 `--folder-token` 时，shortcut 会保留空的 `point.mount_key`，Lark Import API 会将其视为“导入到调用者根目录”。

### 支持的文件类型转换

本地文件扩展名与目标云文档类型的对应关系如下：

| 本地文件扩展名 | 可导入为 | 说明 |
|--------------|---------|------|
| `.docx`, `.doc` | `docx` | Microsoft Word 文档 |
| `.txt` | `docx` | 纯文本文件 |
| `.md`, `.markdown`, `.mark` | `docx` | Markdown 文档 |
| `.html` | `docx` | HTML 文档 |
| `.xlsx` | `sheet`, `bitable` | Microsoft Excel 表格 |
| `.xls` | `sheet` | Microsoft Excel 97-2003 表格 |
| `.csv` | `sheet`, `bitable` | CSV 数据文件 |

> [!IMPORTANT]
> 用户口头说的 “Base” / “多维表格” / “bitable”，在命令里统一对应 `--type bitable`。
>
> 文件扩展名与目标文档类型必须匹配，否则会返回验证错误：
> - 文档类文件（.docx, .doc, .txt, .md, .html）**只能**导入为 `docx`
> - `.xlsx` / `.csv` 文件**只能**导入为 `sheet` 或 `bitable`
> - `.xls` 文件**只能**导入为 `sheet`
> - 例如：`.csv` 文件不能导入为 `docx`，`.md` 文件不能导入为 `sheet`

> [!IMPORTANT]
> 如果在线文档是**以应用身份（bot）导入创建**的，如 `lark-cli drive +import --as bot`，当某次结果**已经返回最终在线文档目标**后，CLI 会**尝试为当前 CLI 用户自动授予该资源的 `full_access`（可管理权限）**。
>
> 这个自动授权有两种触发时机：
> - `drive +import` 的内置轮询窗口内已经完成，直接在 `+import` 中进行自动授权
> - `drive +import` 先返回 `ready=false` / `timed_out=true`，之后你再执行 `lark-cli drive +task_result --scenario import --ticket <TICKET>`，当该查询第一次拿到最终在线文档目标时会自动授权
>
> 只有在已经拿到最终在线文档目标的那次结果里，才会返回 `permission_grant` 字段，明确说明授权结果：
> - `status = granted`：当前 CLI 用户已获得该导入结果的可管理权限
> - `status = skipped`：本地没有可用的当前用户 `open_id`，或当前结果还没有可授权目标，因此不会自动授权；如需补齐用户授权，由 agent 在后台发起 `lark-cli auth login` 并把授权链接发给用户点击，再继续使用应用身份（bot）授予当前用户权限
> - `status = failed`：导入已成功返回最终在线文档，但自动授权用户失败；会带上失败原因，并提示稍后重试或继续使用 bot 身份处理该文档
>
> `permission_grant.perm = full_access` 表示该资源已授予“可管理权限”。
>
> **不要擅自执行 owner 转移。** 如果用户需要把 owner 转给自己，必须单独确认。

### 文件大小限制

除扩展名与目标类型匹配外，`drive +import` 还会在本地上传前校验格式级大小限制：

| 本地文件扩展名 | 导入目标 | 大小上限 |
|--------------|---------|---------|
| `.docx`, `.doc` | `docx` | 600MB |
| `.txt` | `docx` | 20MB |
| `.md`, `.mark`, `.markdown` | `docx` | 20MB |
| `.html` | `docx` | 20MB |
| `.xlsx` | `sheet`, `bitable` | 800MB |
| `.csv` | `sheet` | 20MB |
| `.csv` | `bitable` | 100MB |
| `.xls` | `sheet` | 20MB |

- 如果文件超出对应上限，shortcut 会在真正上传前直接返回验证错误。
- “超过 20MB 自动切换分片上传”只表示上传链路会切到 multipart，不代表所有格式都允许导入超过 20MB 的文件。

- 若导入任务执行失败，会返回失败时的 `job_status` 及错误信息。
- 若内置轮询超时但任务仍在处理中，shortcut 会成功返回，并带上：
  - `ready=false`
  - `timed_out=true`
  - `next_command`：可直接复制执行的后续查询命令，例如 `lark-cli drive +task_result --scenario import --ticket <TICKET>`
- 若使用 `--as bot` 且内置轮询窗口内已经拿到最终在线文档，输出还会额外带上 `permission_grant`，用于说明是否已自动为当前 CLI 用户授予可管理权限。
- 若使用 `--as bot` 但当前只返回 `ready=false`，此时还不会返回 `permission_grant`；应继续执行返回值里的 `next_command`，等 `drive +task_result --scenario import` 拿到最终文档后再触发自动授权。
- 如果文件扩展名不被支持，执行时将抛出验证错误。

### 超时后的继续查询

当 `+import` 的内置轮询窗口结束但任务尚未完成时，使用返回结果中的 `ticket` 继续查询：

```bash
lark-cli drive +task_result --scenario import --ticket <TICKET>
```

如果这里最终返回 `ready=true` 且使用的是 `--as bot`，结果还会额外带上 `permission_grant`，用于说明是否已自动为当前 CLI 用户授予可管理权限。

> [!CAUTION]
> `drive +import` 是**写入操作** —— 执行前必须确认用户意图。

## 参考

- [lark-drive](../SKILL.md) -- 云空间全部命令
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
