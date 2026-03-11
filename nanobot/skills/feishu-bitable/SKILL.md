---
name: feishu-bitable
description: 飞书多维表 Python API + 命令行工具。支持日报和任务的增删改查操作。
---

# Feishu Bitable

飞书多维表统一操作工具，提供 **Python API** 和 **命令行** 两种使用方式。

## 功能

- **日报管理**：录入、查询、更新、删除日报
- **任务管理**：录入、查询、更新、删除任务
- **字段查询**：获取表字段定义
- **双模式支持**：Python API 导入使用 + 命令行快速操作

## 使用方法

### Python API

```python
from skills.feishu_bitable import (
    daily_add, daily_query, daily_update, daily_delete,
    task_add, task_query, task_update, task_delete,
    get_fields
)

# ============ 日报操作 ============

# 录入日报
result = daily_add(
    user_id="ou_fb8ed1f2da72bd32207a7c75494fd8a0",
    date="2026-03-06",
    project="HiperOne",
    content="完成飞书 API 集成",
    hours=2
)
print(result)  # {"record_id": "recxxx", "success": True}

# 查询日报
records = daily_query(
    user_id="ou_fb8ed1f2da72bd32207a7c75494fd8a0",
    date_from="2026-03-01",
    date_to="2026-03-06",
    limit=10
)

# 更新日报
result = daily_update(
    record_id="recvd4wBADF91m",
    fields={"时长": "8", "工作内容": "更新后的内容"}
)

# 删除日报
result = daily_delete(record_id="recvd4wBADF91m")


# ============ 任务操作 ============

# 录入任务
from datetime import datetime, timedelta
deadline = int((datetime.now() + timedelta(days=7)).timestamp() * 1000)

result = task_add(
    name="测试 API",
    serial=1001,
    project="recvcGZsmzHcCF",  # 项目记录 ID
    executor="ou_fb8ed1f2da72bd32207a7c75494fd8a0",
    status="进行中",
    deadline=deadline,
    hours=4,
    description="任务描述"
)

# 查询任务
tasks = task_query(
    executor="ou_fb8ed1f2da72bd32207a7c75494fd8a0",
    status="进行中",
    limit=10
)

# 更新任务
result = task_update(
    record_id="recvd4wDkvSrQL",
    fields={"预计耗时": 8, "状态": ["已完成"]}
)

# 删除任务
result = task_delete(record_id="recvd4wDkvSrQL")


# ============ 字段查询 ============

# 获取日报表字段
fields = get_fields("tblYWOnDxGsVSfDN")

# 获取任务表字段
fields = get_fields("tblH6xn2dp6E1UtD")
```

### 命令行

```bash
cd skills/feishu-bitable

# ============ 日报操作 ============

# 录入日报
python3 scripts/bitable.py daily add \
  --user-id ou_fb8ed1f2da72bd32207a7c75494fd8a0 \
  --date 2026-03-06 \
  --project HiperOne \
  --content "完成飞书 API 集成" \
  --hours 2

# 查询日报
python3 scripts/bitable.py daily query --limit 10

# 按用户查询
python3 scripts/bitable.py daily query \
  --user-id ou_fb8ed1f2da72bd32207a7c75494fd8a0 \
  --limit 5

# 更新日报
python3 scripts/bitable.py daily update \
  --record-id recvd4wBADF91m \
  --fields '{"时长": "8", "工作内容": "更新内容"}'

# 删除日报
python3 scripts/bitable.py daily delete --record-id recvd4wBADF91m


# ============ 任务操作 ============

# 录入任务
python3 scripts/bitable.py task add \
  --name "测试 API" \
  --serial 1001 \
  --project recvcGZsmzHcCF \
  --executor ou_fb8ed1f2da72bd32207a7c75494fd8a0 \
  --status 进行中 \
  --deadline 7 \
  --hours 4 \
  --description "任务描述"

# 查询任务
python3 scripts/bitable.py task query --limit 10

# 按执行人查询
python3 scripts/bitable.py task query \
  --executor ou_fb8ed1f2da72bd32207a7c75494fd8a0 \
  --limit 5

# 更新任务
python3 scripts/bitable.py task update \
  --table tblH6xn2dp6E1UtD \
  --record-id recvd4wDkvSrQL \
  --fields '{"预计耗时": 8}'

# 删除任务
python3 scripts/bitable.py task delete \
  --table tblH6xn2dp6E1UtD \
  --record-id recvd4wDkvSrQL


# ============ 字段查询 ============

# 获取日报表字段
python3 scripts/bitable.py fields --table tblYWOnDxGsVSfDN

# 获取任务表字段
python3 scripts/bitable.py fields --table tblH6xn2dp6E1UtD
```

## 配置

通过系统环境变量配置飞书应用凭据（与其他飞书 skill 共用）：

```bash
export NANOBOT_CHANNELS__FEISHU__APP_ID=cli_xxx
export NANOBOT_CHANNELS__FEISHU__APP_SECRET=xxx
```

多维表 App Token 已内置（`JXdtbkkchaSXmksx6eFc2Eatn45`）。

## 数据表结构

### 日报表 (tblYWOnDxGsVSfDN)

| 字段名 | 类型 | 格式 |
|--------|------|------|
| 日期 | 日期 | `"YYYY-MM-DD"` |
| 姓名 | 人员 | `[{"id": "ou_xxx"}]` |
| 项目 | 文本 | `"HiperOne"` |
| 工作内容 | 文本 | `"工作内容"` |
| 时长 | 数字 | `"2"` (字符串) |
| 关联项目 | 关联 | `["recxxx"]` |

### 任务表 (tblH6xn2dp6E1UtD)

| 字段名 | 类型 | 格式 |
|--------|------|------|
| 任务名称 | 文本 | `"任务名称"` |
| 序号 | 数字 | `1001` |
| 项目 | 关联 | `["recxxx"]` |
| 执行人 | 人员 | `[{"id": "ou_xxx"}]` |
| 状态 | **多选** | `["进行中"]` |
| 截止日期 | 日期 | `1773382257712` (毫秒时间戳) |
| 预计耗时 | 数字 | `4` (数字) |
| 任务描述 | 文本 | `"描述"` |

## 用户飞书 ID 速查

| 姓名 | 飞书 ID |
|------|---------|
| 柏祖印 | ou_5c4a8ef941b00f4df52b333057b74147 |
| 陈宇虹 | ou_d051bd4c6b3c9edd6e33bf0d4470c3ed |
| 陈晓芸 | ou_754f4590a35ebc9aa4318f930ec8415f |
| 狄亚慧 | ou_ab48c62bb7f9edfd2bf5d3cffd6191d1 |
| 范上智 | ou_b0d8b00dfcda9e973b6ba93d87352997 |
| 冯宁前 | ou_9652f9b333db69ebee6a6569c5a76832 |
| 郭恒 | ou_f90a6399eb9db4288ea66d2634e5f25e |
| 郭晓龙 | ou_e2b79b387a397e8f8455cbad07b601dd |
| 贾平元 | ou_0e57f53ae7a75e81356ae9f3738e897a |
| 李盟 | ou_df343d6befda58b1f45037ff4055f440 |
| **李元明** | ou_fb8ed1f2da72bd32207a7c75494fd8a0 |
| 李哲民 | ou_545053f59e2588bce6f23a39628bc15c |
| 刘晨 | ou_0c066d83d0025845c4737af0b35e1b13 |
| 刘世伟 | ou_6d4383a54a8c04264f427be9d1792b8a |
| 罗皓 | ou_26e70bd8272d50612951c1a5ce211491 |
| 欧阳玉峰 | ou_b1c7849aa96e6c32d8ae9bc90159181a |
| 亓兴中 | ou_b82526ca9b13544d6a7cef7b32a44e3c |
| 汪龙龙 | ou_2f1c4de0c64107f7514302cd803ffc00 |
| 王一晴 | ou_35060be4eff3352c2f8dcc90e0b507d1 |
| 王依琪 | ou_396bba347146ffa0fcd53d8c61622f80 |
| 杨鹏飞 | ou_4a21d3fed9913150ad2bbffc7f0b64b2 |
| 张立 | ou_781e3bd62f19a4351bf53fe57f8d48ae |
| 张露然 | ou_e3411798253b9b63715f1760ce5a387f |
| 卓黎冰 | ou_4c5d5d932c85c58ce17dd5490d36a060 |
| 邹立权 | ou_17d38105de58c88cb2a689ddb1d6be22 |
| 许真真 | ou_b52c099faeb095aa7fe6e44a126c438b |

## 文件结构

```
skills/feishu-bitable/
├── SKILL.md              # 技能文档
├── __init__.py           # Python API 模块
└── scripts/
    └── bitable.py        # 命令行工具
```

## 测试状态

✅ **Python API: 9/9 通过** | **命令行：8/8 通过** (2026-03-06 16:15)

### Python API 测试

| 测试项目 | 状态 |
|---------|------|
| get_fields | ✅ |
| daily_add | ✅ |
| daily_query | ✅ |
| daily_update | ✅ |
| daily_delete | ✅ |
| task_add | ✅ |
| task_query | ✅ |
| task_update | ✅ |
| task_delete | ✅ |

### 命令行测试

| 测试项目 | 状态 |
|---------|------|
| help | ✅ |
| fields | ✅ |
| daily add | ✅ |
| daily query | ✅ |
| daily update | ✅ |
| daily delete | ✅ |
| task add | ✅ |
| task query | ✅ |
| task update | ✅ |
| task delete | ✅ |

## 常见错误码

| Code | Message | Solution |
|------|---------|----------|
| 1254066 | Field format error | 检查字段类型格式 |
| 1254060 | Invalid field value | 验证字段值合法性 |
| 1254067 | LinkFieldConvFail | 关联字段需用记录 ID 列表 |
| 1254063 | MultiSelectFieldConvFail | 多选字段需用字符串列表 |
| 99991663 | Permission denied | 检查应用权限 |
| 1254302 | Record not found | 验证记录 ID 存在 |

---

*Last updated: 2026-03-06 16:15 (Python API + CLI 双模式)*
