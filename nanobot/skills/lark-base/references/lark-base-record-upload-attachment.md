# base +record-upload-attachment

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

上传本地文件到当前 Base，并把附件值写入指定记录的附件字段。

## 推荐命令

```bash
lark-cli base +record-upload-attachment \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --record-id rec_xxx \
  --field-id fld_attach \
  --file ./report.pdf

lark-cli base +record-upload-attachment \
  --base-token app_xxx \
  --table-id tbl_xxx \
  --record-id rec_xxx \
  --field-id "附件" \
  --file ./report.pdf \
  --name "Q1-final.pdf"
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base-token <token>` | 是 | Base Token |
| `--table-id <id_or_name>` | 是 | 表 ID 或表名 |
| `--record-id <id>` | 是 | 记录 ID |
| `--field-id <id_or_name>` | 是 | 附件字段 ID 或字段名 |
| `--file <path>` | 是 | 本地文件路径，最大 20MB |
| `--name <name>` | 否 | 写入附件字段时显示的文件名，默认使用本地文件名 |


## 工作流

> [!CAUTION]
> 这是写入操作。用户已经明确要上传到某条记录的某个附件字段时可直接执行；如果 `record-id` 或目标字段仍有歧义，再先确认。

## 坑点

- ⚠️ 目标字段必须是 `attachment` 字段。

## 参考

- [lark-base-record.md](lark-base-record.md) — record 索引页
- [lark-base-shortcut-record-value.md](lark-base-shortcut-record-value.md) — 记录值格式详解
