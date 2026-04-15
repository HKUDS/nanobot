
# drive +upload

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

上传本地文件到飞书云空间。

## 命令

```bash
# 推荐：使用 shortcut 一步上传
lark-cli drive +upload --file ./report.pdf --folder-token fldbc_xxx

# 自定义上传后的文件名
lark-cli drive +upload --file ./report.pdf --name "季度总结.pdf"

# 生成可用临时下载链接的上传方式（素材上传，适用于后续用 curl 下载）
# 注意：需要可写 docx 文档 ID（用于挂载素材 block），且文件最大 20MB
lark-cli drive +upload --as-media --doc docx_xxx --file ./report.pdf

# 取出 tmp_download_url 后可直接 curl 下载
curl -L -o report.pdf "<TMP_DOWNLOAD_URL>"

# 原生命令（高级/分片上传）：预上传 + 完成上传
lark-cli drive files upload_prepare --data '{
  "file_name": "report.pdf",
  "parent_type": "explorer",
  "parent_node": "fldbc_xxx",
  "size": 1048576
}'
lark-cli drive files upload_finish --data '{
  "upload_id": "<UPLOAD_ID>",
  "block_num": 1
}'

# 查看完整参数定义
lark-cli schema drive.files.upload_prepare
```

> [!IMPORTANT]
> 如果文件是**以应用身份（bot）上传**的，如 `lark-cli drive +upload --as bot` 在上传成功后，CLI 会**尝试为当前 CLI 用户自动授予该文件的 `full_access`（可管理权限）**。
>
> 以应用身份上传时，结果里会额外返回 `permission_grant` 字段，明确说明授权结果：
> - `status = granted`：当前 CLI 用户已获得该文件的可管理权限
> - `status = skipped`：本地没有可用的当前用户 `open_id`，因此不会自动授权；如需补齐用户授权，由 agent 在后台发起 `lark-cli auth login` 并把授权链接发给用户点击，再继续使用应用身份（bot）授予当前用户权限
> - `status = failed`：文件已上传成功，但自动授权用户失败；会带上失败原因，并提示稍后重试或继续使用 bot 身份处理该文件
>
> `permission_grant.perm = full_access` 表示该资源已授予“可管理权限”。
>
> **不要擅自执行 owner 转移。** 如果用户需要把 owner 转给自己，必须单独确认。

参数（预上传 `--data` JSON body）：

| 字段 | 必填 | 说明 |
|------|------|------|
| `file_name` | 是 | 文件名 |
| `parent_type` | 是 | 父节点类型，如 `"explorer"` |
| `parent_node` | 是 | 父节点 token（文件夹 token） |
| `size` | 是 | 文件大小（字节） |

> [!CAUTION]
> 这是**写入操作** —— 执行前必须确认用户意图。

## 参考

- [lark-drive](../SKILL.md) -- 云空间全部命令
- [lark-shared](../../lark-shared/SKILL.md) -- 认证和全局参数
