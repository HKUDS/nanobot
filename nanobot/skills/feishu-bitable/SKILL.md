---
name: feishu-bitable
description: 飞书多维表格 — 数据表 CRUD、智能字段转换、日报/任务录入、批量操作。当用户提及多维表格、bitable、数据表、日报录入、任务录入、写日报、记录任务时，务必先读取此技能。
metadata:
  requires:
    - type: binary
      name: python3
---

# 飞书多维表格 (Bitable)

飞书多维表格 API，支持数据表 CRUD、字段定义查询、智能字段格式转换、日报/任务便捷函数、批量操作。

## 使用流程

1. 根据下方 API 函数说明确认所需操作
2. 通过 `exec` 工具调用脚本执行

## API 函数

### bitable_list_tables

获取数据表列表。

```
python3 scripts/feishu_bitable.py tables --app-token bascnXXX
```

### bitable_get_fields

获取字段定义（创建/更新前建议先调用以确认字段名）。

```
python3 scripts/feishu_bitable.py fields --app-token bascnXXX --table-id tblXXX
```

### bitable_list_records

查询记录，支持 filter 表达式。

```
python3 scripts/feishu_bitable.py list --app-token bascnXXX --table-id tblXXX --limit 200
python3 scripts/feishu_bitable.py list --app-token bascnXXX --table-id tblXXX --filter 'CurrentValue.[项目]="xxx"'
```

### bitable_add_record / bitable_add_record_smart

创建记录。`add` 需按飞书 API 格式传字段；`add-smart` 自动转换日期、用户、多选等格式。

```
python3 scripts/feishu_bitable.py add --app-token bascnXXX --table-id tblXXX --fields '{"字段名":"值"}'
python3 scripts/feishu_bitable.py add-smart --app-token bascnXXX --table-id tblXXX --fields '{"任务名称":"测试","执行人":"ou_xxx","计划截止时间":"2026-03-14","状态":["待处理"]}'
```

### bitable_update_record / bitable_update_record_smart

更新记录。`update-smart` 自动转换字段格式。

```
python3 scripts/feishu_bitable.py update --app-token bascnXXX --table-id tblXXX --record-id recXXX --fields '{"状态":"完成"}'
python3 scripts/feishu_bitable.py update-smart --app-token bascnXXX --table-id tblXXX --record-id recXXX --fields '{"状态":"完成","实际完成时间":"2026-03-13"}'
```

### bitable_delete_record

删除记录。

```
python3 scripts/feishu_bitable.py delete --app-token bascnXXX --table-id tblXXX --record-id recXXX
```

### bitable_batch_add_records / batch_update / batch_delete

批量操作（单次最多 500 条）。`batch-add` 支持 `--smart` 启用智能转换。

```
python3 scripts/feishu_bitable.py batch-add --app-token bascnXXX --table-id tblXXX --records '[{"任务名称":"A"},{"任务名称":"B"}]'
python3 scripts/feishu_bitable.py batch-add --app-token bascnXXX --table-id tblXXX --records '[{"任务名称":"A","执行人":"ou_xxx"}]' --smart
python3 scripts/feishu_bitable.py batch-update --app-token bascnXXX --table-id tblXXX --records '[{"record_id":"recXXX","fields":{"状态":"完成"}}]'
python3 scripts/feishu_bitable.py batch-delete --app-token bascnXXX --table-id tblXXX --record-ids '["recXXX","recYYY"]'
```

### bitable_add_daily_report / bitable_query_daily_reports

录入日报、查询日报。脚本内预置 `BITABLE_APP_TOKEN`、`DAILY_TABLE_ID`，可修改脚本或传参覆盖。

```
python3 scripts/feishu_bitable.py daily-add --user-id ou_xxx --date 2026-03-13 --project "项目名" --content "完成开发" --hours 8
python3 scripts/feishu_bitable.py daily-query --limit 200
python3 scripts/feishu_bitable.py daily-query --limit 500 --filter 'CurrentValue.[项目]="xxx"'
python3 scripts/feishu_bitable.py daily-query --limit 200 --page-token xxx --app-token bascnXXX --table-id tblXXX
```

### bitable_add_task / bitable_query_tasks

录入任务、查询任务。`--project` 为项目 record_id，`--executor` 为执行人 open_id。

```
python3 scripts/feishu_bitable.py task-add --name "任务名" --project recXXX --executor ou_xxx --status 待处理 --deadline 7
python3 scripts/feishu_bitable.py task-query --limit 200
python3 scripts/feishu_bitable.py task-query --limit 500 --filter 'CurrentValue.[状态]="进行中"'
python3 scripts/feishu_bitable.py task-query --limit 200 --page-token xxx --table tblXXX --app-token bascnXXX
```

## 智能字段转换

`add-smart`、`update-smart`、`batch-add --smart` 会自动转换以下格式。`add_record_smart` / `update_record_smart` 会缓存字段定义，避免重复 API 调用。日期使用 UTC+8 时区。

| 字段类型 | 输入格式 | 自动转换为 |
|---------|---------|-----------|
| DateTime | `"2026-03-14"` | 毫秒时间戳 |
| DateTime | `1773417600000` | 保持不变 |
| User | `"ou_xxx"` | `[{"id":"ou_xxx"}]` |
| MultiSelect | `"选项"` | `["选项"]` |
| Number | `"8"` | `8` |

## 常见错误

| 错误码 | 提示 |
|--------|------|
| 1254045 | 字段名不存在，请先调用 bitable_get_fields 查看字段定义 |
| 1254064 | 日期字段格式错误，请使用毫秒时间戳或 YYYY-MM-DD 格式 |
| 1254066 | 用户字段格式错误，请提供有效的 open_id 或 union_id |
| 1254063 | 单选/多选字段值错误，请检查选项是否存在 |

## 预置常量

脚本内可配置 `BITABLE_APP_TOKEN`、`DAILY_TABLE_ID`、`TASK_TABLE_ID`、`PROJECT_TABLE_ID`。日报/任务便捷函数使用这些默认值，其他命令需显式传 `--app-token`、`--table-id`。

## 所需权限

- `bitable:app` — 读写多维表格
- `bitable:app:readonly` — 只读多维表格

## 凭据

自动读取 `~/.hiperone/config.json` 或环境变量 `NANOBOT_CHANNELS__FEISHU__APP_ID` / `NANOBOT_CHANNELS__FEISHU__APP_SECRET`，无需手动配置。

## 测试

运行 `python test_feishu_bitable.py` 可测试本技能全部 14 个函数。
