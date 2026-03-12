# 人事 (HR)

飞书人事 API (corehr/v1)，查询请假记录和员工花名册。

## API 函数

### hr_leave_request_history

查询请假记录。

```python
from feishu_api import hr_leave_request_history

data = hr_leave_request_history(
    employment_id="xxx",          # 雇员 ID（可选）
    start_date="2026-01-01",      # 可选
    end_date="2026-03-12",        # 可选
    page_size=50,
)
# data["leave_request_list"] -> [
#   {leave_request_id, employment_id, leave_type_id, start_date, end_date, ...}
# ]
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py hr leave-history --employment-id xxx --start-date 2026-01-01 --end-date 2026-03-12
python3 ${SKILL_DIR}/scripts/feishu_api.py hr leave-history --limit 50
```

### hr_get_employee

查询员工花名册信息。

```python
from feishu_api import hr_get_employee

data = hr_get_employee("employment_id_xxx")
# data["employment"] -> {id, employee_number, person, department, job, ...}
```

**CLI**:
```bash
python3 ${SKILL_DIR}/scripts/feishu_api.py hr employee --employment-id xxx
```

## 说明

- `employment_id` 是飞书人事系统中的雇员 ID，不同于 `open_id` 或 `employee_id`
- 需要企业开通飞书人事模块
- 请假记录查询也可通过审批模块的 `approval_list_instances` 实现

## 所需权限

- `corehr:leave:readonly` — 查看请假记录
- `corehr:employment:readonly` — 查看员工信息
