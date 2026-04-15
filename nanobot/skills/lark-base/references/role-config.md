# 飞书多维表格角色权限配置详解

> **返回**: [SKILL.md](../SKILL.md) | **相关**: [role-create](lark-base-role-create.md) · [role-update](lark-base-role-update.md) · [role-get](lark-base-role-get.md)

本文档详细说明角色权限（AdvPermBaseRoleConfig）的完整 JSON 结构，供 `+role-create` 和 `+role-update` 构造 `--json` 参数时参考。

## 📋 目录

- [顶层结构 (AdvPermBaseRoleConfig)](#顶层结构-advpermbaseroleconfig)
- [角色类型 (RoleType)](#角色类型-roletype)
- [Base 级权限 (BaseRuleMap)](#base-级权限-baserulemap)
- [仪表盘权限 (DashboardRule)](#仪表盘权限-dashboardrule)
- [文档权限 (DocxRule)](#文档权限-docxrule)
- [数据表权限 (TableRule)](#数据表权限-tablerule)
    - [表级权限 (TablePerm)](#表级权限-tableperm)
    - [视图权限 (ViewRule)](#视图权限-viewrule)
    - [字段权限 (FieldRule)](#字段权限-fieldrule)
    - [记录权限 (RecordRule)](#记录权限-recordrule)
    - [筛选条件 (FilterRuleGroup)](#筛选条件-filterrulegroup)
- [默认权限策略与风控规则](#默认权限策略与风控规则)
    - [默认关闭项](#默认关闭项)
    - [权限对象选择](#权限对象选择)
    - [记录操作默认策略](#记录操作默认策略)
    - [field_perms 构造 SOP](#field_perms-构造-sop)
    - [视图权限默认策略](#视图权限默认策略)

---

## 顶层结构 (AdvPermBaseRoleConfig)

```json
{
  "role_name": "财务审核员",
  "role_type": "custom_role",
  "base_rule_map": { "copy": false, "download": false },
  "table_rule_map": { "订单表": { "perm": "edit", "...": "..." } },
  "dashboard_rule_map": { "销售看板": { "perm": "read_only" } },
  "docx_rule_map": { "文档A": { "perm": "edit", "allow_download": true } }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|----|------|
| `role_name` | string | 是  | 角色名称，不能为空 |
| `role_type` | string | 是  | 角色类型，见 [RoleType](#角色类型-roletype) |
| `base_rule_map` | map\<string, bool\> | 是  | Base 级权限，见 [BaseRuleMap](#base-级权限-baserulemap) |
| `table_rule_map` | map\<string, TableRule\> | 否  | 数据表权限，key 为表名 |
| `dashboard_rule_map` | map\<string, DashboardRule\> | 否  | 仪表盘权限，key 为仪表盘名称 |
| `docx_rule_map` | map\<string, DocxRule\> | 否  | 文档权限（仅单品模式），key 为文档名称 |

---

## 角色类型 (RoleType)

| 值 | 说明 |
|------|------|
| `editor` | 系统角色：编辑者 |
| `reader` | 系统角色：阅读者 |
| `custom_role` | 自定义角色 |

**注意**:
- 创建接口（`+role-create`）仅支持 `custom_role`
- 更新接口（`+role-update`）支持  `editor` / `reader` / `custom_role`

---

## Base 级权限 (BaseRuleMap)

1. 默认值均为 `false`，当需要启用时设置为 `true`。
2. 在新增角色和修改角色时需要默认带上这个字段，**严禁**在用户未明确要求的情况下将其设置为 `true`。

```json
{
  "base_rule_map": {
    "copy": true,
    "download": false
  }
}
```

| Key | 说明 |
|-----|------|
| `copy` | 允许复制多维表格内容 |
| `download` | 允许创建副本、下载、打印多维表格 |

---

## 仪表盘权限 (DashboardRule)

```json
{
  "dashboard_rule_map": {
    "销售看板": { "perm": "read_only" },
    "内部数据": { "perm": "no_perm" }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `perm` | string | 仪表盘权限 |

**perm 可选值**:

| 值 | 说明 |
|----|------|
| `read_only` | 仅可阅读 |
| `no_perm` | 无权限 |

---

## 文档权限 (DocxRule)

> ⚠️ 仅在单品模式（`is_base_solo = true`）下可用。

```json
{
  "docx_rule_map": {
    "文档A": { "perm": "edit", "allow_download": true },
    "文档B": { "perm": "read_only" }
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `perm` | string | 是 | 文档权限 |
| `allow_download` | bool | 否 | 是否允许下载/导出 |

**perm 可选值**:

| 值 | 说明 |
|----|------|
| `edit` | 可编辑 |
| `read_only` | 仅可阅读 |
| `no_perm` | 无权限 |

---

## 数据表权限 (TableRule)

```json
{
  "table_rule_map": {
    "订单表": {
      "perm": "edit",
      "view_rule": { "..." : "..." },
      "record_rule": { "..." : "..." },
      "field_rule": { "..." : "..." }
    },
    "用户表": {
      "perm": "read_only"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `perm` | string | 表级权限，见 [TablePerm](#表级权限-tableperm) |
| `view_rule` | ViewRule | 视图权限配置 |
| `record_rule` | RecordRule | 记录权限配置 |
| `field_rule` | FieldRule | 字段权限配置 |

**注意**: 当 `perm` 为 `no_perm` 时，`view_rule`、`record_rule`、`field_rule` 均无须再设置。

---

### 表级权限 (TablePerm)

| 值 | 说明 |
|----|------|
| `manage` | 可管理 |
| `edit` | 可编辑 |
| `read_only` | 仅可阅读 |
| `no_perm` | 无权限（此时不能再设置视图、记录和字段的权限） |

---

### 视图权限 (ViewRule)

```json
{
  "view_rule": {
    "allow_edit": true,
    "visibility": {
      "all_visible": false,
      "visible_views": ["表格视图", "看板视图"]
    }
  }
}
```

| 字段 | 类型 | 说明                         |
|------|------|----------------------------|
| `allow_edit` | bool | 可新增、删除、修改视图，未提及默认为 `false` |
| `visibility` | object | 可见的视图配置                    |
| `visibility.all_visible` | bool | 是否全部可见                     |
| `visibility.visible_views` | []string | 可见视图名称 列表                  |

**⚠️ 核心规则：`view_rule` 必须同时包含 `allow_edit` 和 `visibility` 两个字段，缺一不可。**

输出 `view_rule` 时，**必须**使用以下完整结构，根据场景选择对应模板：

```json
// 情况 A：用户要求可编辑/新增/删除视图 → allow_edit 设为 true
{
  "view_rule": {
    "allow_edit": true,
    "visibility": {
      "all_visible": true
    }
  }
}

// 情况 B：用户未提及具体视图，未要求编辑视图 → 全部可见、不可编辑
{
  "view_rule": {
    "allow_edit": false,
    "visibility": {
      "all_visible": true
    }
  }
}

// 情况 C：用户提及了具体视图 → 仅指定视图可见
{
  "view_rule": {
    "allow_edit": false,
    "visibility": {
      "all_visible": false,
      "visible_views": ["表格视图", "看板视图"]
    }
  }
}
```

**注意**:
- 当 `all_visible` 为 `false` 时，`visible_views` 不可为空，必须指定至少一个可见视图
- `biz_type` 为 `query_form_view` 的视图不可放在 `visible_views` 中（不能配置可见性）

---

### 字段权限 (FieldRule)

```json
{
  "field_rule": {
    "field_perm_mode": "specify",
    "field_perms": {
      "金额": "edit",
      "备注": "read",
      "密码": "no_perm"
    },
    "allow_edit_and_modify_option_fields": [],
    "allow_edit_and_download_file_fields": []
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `field_perm_mode` | string | 字段权限模式 |
| `field_perms` | map\<string, string\> | 字段名 → 权限，仅 `field_perm_mode` 为 `specify` 时有效 |
| `allow_edit_and_modify_option_fields` | []string | 允许增删改选项的字段名列表 |
| `allow_edit_and_download_file_fields` | []string | 允许下载附件的字段名列表 |

**field_perm_mode 可选值**:

| 值 | 说明 |
|----|------|
| `all_edit` | 所有字段可编辑，但选项不可增删改 |
| `all_read` | 所有字段可读 |
| `specify` | 指定字段权限（可进一步设置 `field_perms` 和选项增删改权限） |
| `no_perm` | 无权限 |

**field_perms 中单个字段的权限值**:

| 值 | 说明 |
|----|------|
| `edit` | 可编辑（含新增和阅读权限） |
| `create` | 可新增（含阅读权限） |
| `read` | 可阅读 |
| `no_perm` | 无权限 |

**⚠️ field_perms 重要规则**:
1. 写入前必须先查看字段的 `type`
2. Formula / Lookup / AutoNumber 类型字段**必须强制**降级为 `read` 或 `no_perm`，**严禁**设为 `edit`
3. 必须输出除 4 个系统字段外的所有字段
4. `allow_edit_and_modify_option_fields`：仅当用户明确要求"允许增删改选项"时才配置，否则必须为空数组 `[]`。仅支持 SingleSelect / MultiSelect 类型，**严禁包含 Stage（流程）类型字段**
5. `allow_edit_and_download_file_fields`：用户没有要求时不要设置，且仅 `field_perm_mode` 为 `specify` 时才能设置

---

### 记录权限 (RecordRule)

```json
{
  "record_rule": {
    "record_operations": ["add"],
    "edit_filter_rule_group": {
      "conjunction": "and",
      "filter_rules": [
        {
          "conjunction": "and",
          "filters": [
            {
              "field_name": "部门",
              "operator": "is",
              "filter_values": ["财务部"]
            }
          ]
        }
      ]
    },
    "other_record_all_read": true
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `record_operations` | []string | 记录操作权限，仅 `TablePerm = edit` 时有效 |
| `edit_filter_rule_group` | FilterRuleGroup | 可编辑记录的筛选条件，范围为所有记录时此字段为空 |
| `other_record_all_read` | bool | 是否可阅读所有记录。都可读时为 `true`，其他情况为 `false` |
| `read_filter_rule_group` | FilterRuleGroup | 可阅读记录的额外筛选规则。仅当可阅读范围与可编辑范围不一致时设置（依赖 `other_record_all_read = false`） |

**record_operations 可选值**:

| 值 | 说明 |
|----|------|
| `add` | 可新增记录 |
| `delete` | 可删除记录 |

---

### 筛选条件 (FilterRuleGroup)

```json
{
  "conjunction": "and",
  "filter_rules": [
    {
      "conjunction": "and",
      "filters": [
        {
          "field_name": "部门",
          "operator": "is",
          "field_type": "SingleSelect",
          "filter_values": ["财务部"]
        }
      ]
    }
  ]
}
```

**FilterRuleGroup 结构**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `conjunction` | string | 逻辑连接词：`and` / `or` |
| `filter_rules` | []FilterRule | 筛选规则数组 |

**FilterRule 结构**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `conjunction` | string | 逻辑连接词，默认 `and` |
| `filters` | []Filter | 筛选条件数组 |

**Filter 结构**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `field_name` | string | 是 | 字段名。仅限 `can_filter` 为 `true` 的字段。`field_type` 为 `CreatedUser` 时必须为空 |
| `operator` | string | 是 | 操作符，见下表 |
| `field_type` | string | 是 | 字段类型。仅支持：SingleSelect / MultiSelect / User / CreatedUser / Stage / Number 类字段（含进度条、评分、货币）及部分 Formula / LookUp 字段（以 `can_filter = true` 为准） |
| `reference_type` | string | 条件 | 引用类型。`field_type` 为公式或引用字段时必须赋值，其他情况不能赋值 |
| `filter_values` | []string | 条件 | 筛选值。`operator` 为 `isEmpty` / `isNotEmpty` 时不设置，`field_type` 为 `User` 时也无需设置，其他情况必须设置。值为选项的 `name` |
| `field_ui_type` | string | 条件 | 该字段有值时一定要填 |
| `is_invalid` | bool | 否 | 判断筛选条件是否有效 |

**operator 可选值**:

| 值 | 说明 |
|----|------|
| `is` | 等于 |
| `isNot` | 不等于 |
| `contains` | 包含 |
| `doesNotContain` | 不包含 |
| `isEmpty` | 为空 |
| `isNotEmpty` | 不为空 |
| `isGreater` | 大于 |
| `isGreaterEqual` | 大于等于 |
| `isLess` | 小于 |
| `isLessEqual` | 小于等于 |

**注意**:
- `field_type`、`field_ui_type`、`reference_type` 在创建/更新角色时由服务端 filterFiller 自动补全，客户端通常只需传 `field_name`、`operator`、`filter_values`

---

## 默认权限策略与风控规则

构造角色配置 JSON 时，采用 **默认拒绝与权限最小化** 策略。用户未明确提及的权限一律不开放，不因"合理猜测""常见做法"主动扩展权限范围。

### 默认关闭项

以下能力在用户未明确说明时**默认关闭**：

| 能力 | 默认值 | 开启条件 |
|------|--------|----------|
| 未提及的数据表的任何访问 | `no_perm` | 用户明确提及该表 |
| 仪表盘访问 | 不配置 | 用户明确提及该仪表盘 |
| `base_rule_map.copy` | `false` | 用户明确要求"允许复制" |
| `base_rule_map.download` | `false` | 用户明确要求"允许下载/打印/副本" |
| `record_operations` 中的 `delete` | 不包含 | 用户明确说"允许删除"或使用强语义（"完全管理""可删改"） |

---

### Editor / Reader 的权限上限规则
1. 对 Editor 与 Reader，系统允许修改其权限配置，但同时施加以下封顶约束：
2. Reader 的任一权限项 不允许超过「仅可阅读」
3. Reader 不允许拥有任何可编辑、可新增、可删除相关权限; Editor 的权限可被修改，但其能力范围受高级权限能力封顶。

### 权限对象选择

**注意**:
- 仅对用户明确指向的权限对象生成配置（明确提及的表名、仪表盘名，或可解析为唯一对象的指代如"当前表""这张表"）
- **严禁**基于业务常识、岗位职责、名称相似性或其他角色的历史配置推断或扩展权限对象
- 用户未明确提及的对象不生成任何权限配置，视为 `no_perm`

---

### 记录操作默认策略

**注意**:
- 用户未提及时，默认包含 `add`，默认不包含 `delete`
- 阅读范围默认对齐编辑范围：用户仅描述可编辑范围、未说明阅读范围时，可阅读范围与可编辑范围保持一致，不主动扩大
- 当可读范围与可编辑范围一致时，**不得**生成 `read_filter_rule_group`；应设置 `other_record_all_read = false` 且 `read_filter_rule_group = null`

**⚠️ 记录操作限制**:
1. `perm` 为 `read_only` 时，`record_rule.record_operations` **只能为空**
2. 同步表（`is_sync = true`）**严禁**新增和删除记录

---

### field_perms 构造 SOP

在生成 `field_perms` 时，**严禁**依赖模糊的"继承"概念，必须按以下步骤执行：

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1. 基准设定 | `perm = edit` → 全部字段预设 `"edit"`；`perm = read_only` → 全部预设 `"read"` | 基于 `base_table_info` 中的全量字段 |
| 2. 物理降级 | Formula / Lookup / AutoNumber 及系统字段 → 强制降级为 `"read"` | 不可变字段严禁设为 `edit` |
| 3. 用户覆盖 | 仅对用户**显式指定**了特定权限的字段应用 `no_perm` / `read` / `create` | 未显式指定的保持基准值 |
| 4. 反筛选误判 | 用于 `filter_rules` 的字段，若基准为 `"edit"` 且用户未要求降级 → **保持 `"edit"`** | 筛选条件不影响字段可编辑性 |
| 5. 筛选依赖兜底 | 出现在 `filter_rules` 中的字段**不允许**遗漏，权限至少为 `"read"` | 最终校验步骤 |

**⚠️ field_perm_mode 选择规则**:
1. 用户以"所有字段""全字段"等整体性表述描述且不要求选项增删改时，**必须**使用 `all_edit` / `all_read`，**严禁**变为逐字段 `specify`
2. 仅在以下情况使用 `specify`：用户明确提出字段级差异需求、不同字段权限目标存在显著差异、或明确要求配置选项增删改权限
3. 系统字段硬性约束导致的自动降级**不视为**差异，不触发 `specify`
4. 对"仅""只能""部分"等约束定语，范围外的字段按定语的反方向设置

**⚠️ 同步表限制**: `is_sync = true` 的表**严禁**设置字段为 `edit` 或 `create`

---

### 视图权限默认策略

**判断流程（必须按顺序执行，命中即停）**:

1. **先判断用户是否提及了具体视图名称**（如"看板视图可见""甘特图不可编辑"等）
  - **是** → `all_visible = false`，`visible_views` 仅包含用户明确提及为"可见"的视图名称（非 viewID）；未提及的视图视为不可见
  - **否**（用户完全未提及任何视图）→ `all_visible = true`
2. `allow_edit` 默认为 `false`，仅当用户明确要求"可编辑视图""可新增/删除视图""可管理视图"时才设为 `true`。设为 `true` 时仍**必须**包含 `visibility` 字段（参考视图权限 情况 A）
3. `all_visible` 为 `false` 时，`visible_views` **不可为空**，必须至少包含一个视图

**❌ 常见错误 — 缺少 `visibility` 字段：**
```json
// 错误！缺少 visibility
{ "view_rule": { "allow_edit": false } }
```
**✅ 正确写法：**
```json
// 即使全部可见，也必须显式写出 visibility
{ "view_rule": { "allow_edit": false, "visibility": { "all_visible": true } } }
```

---

### 字段类型与筛选算子的强约束关系

当字段被用于记录筛选条件时，其字段类型（FieldType）与可用算子（Operator）存在固定绑定关系：

**User / CreatedUser 类型字段：**
- 仅允许使用 `contains` 算子
- 不允许使用 `is`、`isNot` 等精确匹配算子
- 筛选条件中无需填写具体值（由系统自动匹配当前成员）

**SingleSelect、Stage 类型字段：**
- `is` 与 `isNot` 算子仅允许用于匹配**单一选项**，不得用于多个值
- 当用户表达"字段值等于/不等于某一个具体选项"（如"出勤状态不等于出勤"）时，Agent 必须使用 `is` / `isNot`，且 filter_values 仅包含单一值。
- 当用户表达"字段值等于/不等于多个选项集合"（如"学历不是专科和其他"）时，Agent 必须使用 `contains` / `doesNotContain`，并将多个选项填入 filter_values。
- `contains` / `doesNotContain`中的filter_values可包含多个值，表示或关系

**MultiSelect 类型字段：**
- `is` / `isNot`：filter_values 允许填写多个选项
  - 当 operator = is 且勾选 A、B 时，语义为该字段**同时包含** A 和 B（A&B），不是"等于 A 或等于 B"
  - 当用户表达"包含任一选项"时，除了可以使用 contains 实现外，也可以使用 is 并且配套通过 filter_rules.conjunction = or 实现
- `contains` / `doesNotContain`：用于表达"包含任一选项/不包含任一选项"，filter_values 可填写多个选项（系统按"任一匹配"处理）；若要表达"等于 A 或等于 B"，应拆成多条筛选条件并用「或」组合。

**百分比字段**
- 对于 query 中“数字”的筛选条件时，如果涉及到百分比，要原封不动地还原用户给你的数值（百分比都变成小数）。比如“大于 20%”则变成“大于 0.2”、“xx 率小于 60”则变成“小于 0.6”。

### 被用于筛选的字段的 field_perms 权限强制要求

当某字段（系统字段没有此要求）被用于「满足特定条件的记录」中的筛选条件时，系统将根据当前数据表权限与记录权限，自动施加以下**不可变约束**：

**筛选字段的读写一致性：**
- 若表权限为 edit，且字段类型属于【可编辑字段】，则筛选字段必须保持 edit 权限，除非用户显式要求降级。
- 严禁因为字段被用作筛选条件而将其降级为 read。筛选条件仅要求字段可见，不要求字段只读。

**新增记录时的字段最低权限：**
- 当且仅当记录权限包含「可新增记录」时，字段至少为可新增（create），用于保证在新增记录时筛选条件字段可被正确写入。
- 若当前记录权限为「仅可阅读」，则不触发该约束。

**字段是否可编辑（edit）不作强制要求**，由具体权限方案决定，不属于 infra 强制约束范围。

上述由系统自动施加的字段权限，不可被手动取消或降级。