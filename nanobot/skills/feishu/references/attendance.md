# 考勤 (Attendance)

飞书考勤 API，查询员工打卡记录。

## API 函数

### get_user_employee_id

通过 open_id 获取 employee_id（考勤查询前置步骤）。

```python
from feishu_api import get_user_employee_id

eid = get_user_employee_id("ou_xxx")
# eid -> "6xxx" (employee_id 字符串)
```

### get_attendance

查询打卡结果。

```python
from feishu_api import get_attendance

data = get_attendance(
    user_ids=["6xxx"],        # employee_id 列表，最多 50 个
    date_from=20260301,       # yyyyMMdd 格式整数
    date_to=20260312,
)
# data["user_task_results"] -> [
#   {employee_name, day, records: [{check_in_result, check_out_result, ...}]}
# ]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py attendance query --user-ids 6xxx --date-from 20260301 --date-to 20260312
```

## 使用流程

1. 先用 `get_user_employee_id(open_id)` 获取 employee_id
2. 再用 `get_attendance([employee_id], date_from, date_to)` 查询打卡

## 所需权限

- `contact:user.employee_id:readonly` — 获取 employee_id
- `attendance:task` — 查询考勤打卡
