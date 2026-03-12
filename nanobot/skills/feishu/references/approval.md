# 审批 (Approval)

使用 `@larksuiteoapi/node-sdk` 在 NestJS 中管理飞书审批流程。

## 所需权限

| 权限标识 | 说明 |
|----------|------|
| `approval:approval` | 读写审批信息 |
| `approval:approval.list:readonly` | 查询审批实例列表 |
| `approval:task` | 审批人操作（同意/拒绝/转交、查询任务） |

## 获取 Approval Code

飞书不提供「列出所有审批定义」的 API，需从管理后台手动获取：

1. 打开 [飞书审批管理后台（开发者模式）](https://www.feishu.cn/approval/admin/approvalList?devMode=on)
2. 找到目标审批 → 点击 **编辑**
3. 从浏览器地址栏复制 `definitionCode=` 后面的值
   - 示例：`https://www.feishu.cn/approval/admin/edit?definitionCode=48D49517-C979-447E-AD93-4BAE0FBC57EA`
4. 获取到的 Code 即为 `approval_code`

## 获取审批定义

查看审批表单结构，了解需要填写哪些字段：

```typescript
const definition = await client.approval.approval.get({
  path: { approval_code: '48D49517-C979-447E-AD93-4BAE0FBC57EA' },
});
// definition.data?.form — 表单控件 JSON 字符串
// definition.data?.node_list — 审批节点列表
```

## 创建审批实例

```typescript
const instance = await client.approval.instance.create({
  data: {
    approval_code: '48D49517-C979-447E-AD93-4BAE0FBC57EA',
    open_id: 'ou_xxx', // 发起人
    form: JSON.stringify([
      {
        id: 'widget001',
        type: 'input',
        value: '出差事由：参加客户交流会',
      },
      {
        id: 'widget002',
        type: 'date',
        value: '2026-03-01T09:00:00+08:00',
      },
    ]),
    // department_id: 'od_xxx', // 多部门用户需填写
  },
});
const instanceCode = instance.data?.instance_code;
```

## 获取审批详情

```typescript
const detail = await client.approval.instance.get({
  path: { instance_id: instanceCode },
});
// detail.data?.status — PENDING / APPROVED / REJECTED / CANCELED
// detail.data?.form — 表单数据
// detail.data?.task_list — 任务列表
// detail.data?.timeline — 审批动态
```

## 查询审批实例列表

```typescript
const list = await client.approval.instance.query({
  data: {
    approval_code: '48D49517-...',
    instance_status: 'PENDING', // PENDING / APPROVED / REJECT / RECALL / ALL
    // user_id: 'ou_xxx', // 按发起人过滤
    // start_time: '1708300800000', // Unix 毫秒时间戳
    // end_time: '1708387200000',
    page_size: 20,
  },
});
```

## 撤回审批

```typescript
await client.approval.instance.cancel({
  data: {
    approval_code: '48D49517-...',
    instance_code: instanceCode,
    user_id: 'ou_xxx', // 审批提交人
  },
});
```

> 撤回需要在审批后台对应审批定义中勾选「允许撤销审批中的申请」或「允许撤销 x 天内通过的审批」。

## 查询审批人待办任务

```typescript
const tasks = await client.approval.task.search({
  data: {
    user_id: 'ou_xxx', // 审批人 open_id
    approval_code: '48D49517-...', // 可选
    task_status: 'PENDING', // PENDING / APPROVED / REJECTED / TRANSFERRED
    page_size: 10,
  },
  params: { user_id_type: 'open_id' },
});
```

也可以通过 `query` 方法查询任务：

```typescript
const taskQuery = await client.approval.task.query({
  params: {
    page_size: 20,
    // page_token: '...',
  },
  data: {
    topic: 'pending', // pending / approved / rejected
    user_id: 'ou_xxx',
  },
});
```

## 同意审批

```typescript
await client.approval.task.approve({
  data: {
    approval_code: '48D49517-...',
    instance_code: instanceCode,
    user_id: 'ou_xxx', // 审批人
    task_id: '7605931414537653476',
    comment: '同意，请注意安全',
    // form: '...', // 部分审批需要补充表单
  },
});
```

## 拒绝审批

```typescript
await client.approval.task.reject({
  data: {
    approval_code: '48D49517-...',
    instance_code: instanceCode,
    user_id: 'ou_xxx',
    task_id: '7605931414537653476',
    comment: '时间冲突，建议改期',
  },
});
```

## 转交审批

```typescript
await client.approval.task.transfer({
  data: {
    approval_code: '48D49517-...',
    instance_code: instanceCode,
    user_id: 'ou_xxx', // 当前审批人
    task_id: '7605931414537653476',
    comment: '转交给主管处理',
    transfer_user_id: 'ou_yyy', // 转交目标
  },
});
```

## 常见表单控件类型

| 控件类型 | 说明 | value 格式 |
|----------|------|------------|
| `input` | 单行文本 | `"文本内容"` |
| `textarea` | 多行文本 | `"文本内容"` |
| `number` | 数字 | `123.45` |
| `date` | 日期 | `"2026-02-12T09:00:00+08:00"` (RFC3339) |
| `leaveGroup` | 请假控件组 | `{"name":"年假","start":"...","end":"...","interval":2.0}` |
| `remedyGroupV2` | 补卡控件组 | `[{"date":"2026-02-12","remedy_time":"...","reason":"..."}]` |
| `tripGroup` | 出差控件组 | `{"schedule":[...],"interval":2.0,"reason":"..."}` |
| `radioV2` | 单选 | `"选项名称"` |
| `checkboxV2` | 多选 | `["选项1","选项2"]` |
| `attachmentV2` | 附件 | 附件 token 列表 |

## 典型工作流

### 发起审批（发起人视角）

1. 获取 approval_code（管理后台或预配置）
2. `client.approval.approval.get()` → 查看表单结构
3. 组装 form JSON → `client.approval.instance.create()` 发起审批
4. `client.approval.instance.get()` → 查询审批状态

### 处理审批（审批人视角）

1. `client.approval.task.search({ data: { user_id, task_status: 'PENDING' } })` → 获取待办
2. 根据标题/申请人匹配目标任务 → 拿到 `task_id` 和 `instance_code`
3. `client.approval.task.approve()` 同意 / `reject()` 拒绝 / `transfer()` 转交

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| 想用 API 列出所有审批定义 | 无此 API，从管理后台获取 approval_code |
| form 传对象而非 JSON 字符串 | `form: JSON.stringify([{id, type, value}])` |
| 忘记传 `task_id` 执行同意/拒绝 | 先通过 `task.search()` 获取 task_id |
| 撤回失败 | 检查审批定义是否允许撤回 |
| `instance_status` 拼写 | `REJECT`（不是 `REJECTED`），`RECALL`（不是 `CANCELED`） |
