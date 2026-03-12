---
name: feishu
description: Use when integrating with Feishu (飞书) or Lark Open Platform using @larksuiteoapi/node-sdk in NestJS/TypeScript. 触发词：飞书, Feishu, Lark, 飞书开放平台, 飞书SDK, 飞书机器人, 飞书消息, 飞书日历, 飞书审批, 多维表格, 飞书通讯录, 飞书考勤, 飞书文档, 云文档, 飞书云空间, 飞书知识库
---

# Feishu Node SDK — NestJS/TypeScript 集成指南

使用 `@larksuiteoapi/node-sdk` 在 NestJS/TypeScript 项目中集成飞书开放平台。

## 集成工作流

**在写任何飞书代码之前，必须按顺序走完以下步骤：**

```
Step 1: 检查项目现状
  ├─ 检查 package.json 是否有 @larksuiteoapi/node-sdk
  ├─ 检查是否有 FeishuService / FeishuModule
  └─ 检查 FeishuService 是否已有凭证（appId 非占位符）

  ↓ 已有凭证（FeishuService 已配置）→ 跳到 Step 4
  ↓ 没有 → Step 2

Step 2: 引导用户创建飞书自建应用
  - 向用户发送以下完整操作清单（假设用户对飞书开放平台不熟悉）：

      1. 打开 https://open.feishu.cn/app → 点击「创建企业自建应用」
      2. 进入应用 →「凭证与基础信息」页面 → 复制 App ID 和 App Secret
      3. 「添加应用能力」→ 开启「机器人」（发消息必须）
      4. 「权限管理」→ 申请以下权限：[根据用户需求列出具体权限，见"常用场景所需权限"表]
      5. 「版本管理与发布」→ 创建版本 → 提交审核（企业管理员审核通过后应用生效）

  - 清单发送完毕后，补充说明：
      「完成以上步骤后，请将 App ID 和 App Secret 发给我，我来帮你写代码。」

  - 等待用户提供真实凭证，**不要使用占位符生成代码**

Step 3: 确认权限 + 保存凭证
  - 根据用户需求告知需申请的权限（见"常用场景所需权限"表）
  - 将凭证写入 FeishuService 源码常量（见"NestJS 模块设置"）
  - 将 App ID 和用途写入 agent.md（见"飞书应用信息持久化"模板）

Step 4: 安装依赖
  - npm install @larksuiteoapi/node-sdk

Step 5: 编写代码
  - 创建 FeishuService（将凭证写入模块顶部常量）
  - 创建 FeishuModule
```

## 代码生成约束

- 所有飞书 API 调用必须放在 NestJS `@Injectable()` Service 的方法中
- `client` 始终通过 `this.client`（FeishuService 内部）或 `this.feishuService.getClient()`（其他 Service）获取
- 数据库操作使用 Drizzle ORM 注入实例（`@Inject(DRIZZLE_DATABASE)`），不使用裸 SQL 或自建连接
- 禁止生成独立运行的 `.ts` 脚本文件

> reference 文件中的代码示例省略了 Service 类包裹，实际使用时 `client` 应替换为 `this.client` 或从注入的 FeishuService 获取。

## 插件优先原则

以下飞书能力存在**平台一方插件**，优先使用插件，不要直接用 node-sdk：

| 需求 | 应使用 | 说明 |
|------|--------|------|
| 发送飞书文本/富文本消息 | **插件**（参考 `plugin_guide`） | 插件在 Client 侧调用，无需后端 Service |
| **发送飞书消息卡片** | **node-sdk**（本文档） | 插件不支持卡片消息，必须用 node-sdk |
| 飞书多维表格增删改查 | **插件**（参考 `plugin_guide`） | 同上 |
| 创建飞书群组 | **插件**（参考 `plugin_guide`） | 同上 |

> **操作步骤（插件）**：先调用 `plugin_guide` 查询候选插件实例 → 调用 `get_plugin_ai_json` 获取 schema → 按文档生成 Client 侧调用代码。

以下能力**无对应插件**，使用本文档的 node-sdk 方案：
消息卡片、日历、审批、云文档、云空间、知识库、权限管理、通讯录、考勤、事件订阅、OAuth 授权。

## Quick Reference

| 模块 | 参考文件 | 简介 |
|------|----------|------|
| 消息 | `references/messaging.md` | 发送文本/富文本消息优先用插件；**卡片消息**用 node-sdk |
| 日历 | `references/calendar.md` | 日程创建/查询/会议室 |
| 审批 | `references/approval.md` | 审批流创建/查询/同意/拒绝 |
| 多维表格 | `references/bitable.md` | 表格/记录/字段 CRUD ⚠️ 优先用插件 |
| 云文档 | `references/doc.md` | 文档创建/Block 读写 |
| 云空间 | `references/drive.md` | 文件夹/文件上传下载 |
| 知识库 | `references/wiki.md` | 知识空间/节点管理 |
| 权限管理 | `references/perm.md` | 文档协作者权限设置 |
| 通讯录 | `references/contacts.md` | 用户/部门信息查询 |
| 考勤 | `references/attendance.md` | 打卡记录/考勤规则查询 |
| 事件订阅 | `references/events.md` | WebSocket 长连接接收事件 |
| OAuth 授权 | `references/oauth.md` | user_access_token 授权 |

> 按需读取 `references/` 下的模块文档获取详细 API 用法和代码示例。

## 飞书应用创建指南

1. 打开 [飞书开发者后台](https://open.feishu.cn/app) → 创建企业自建应用
2. 进入「凭证与基础信息」页面，复制 **App ID** 和 **App Secret** 发给开发者
3. 添加应用能力 → 开启**机器人**（发消息必需）
4. 权限管理 → 申请对应模块的 API 权限（见下方权限映射表）
5. 安全设置 → 配置**通讯录权限范围**（使用通讯录/考勤 API 必需，设为「全部成员」或指定部门）
6. 可用范围 → 添加需要使用该应用的人员或部门（默认仅创建者可用）
7. 版本管理与发布 → 创建版本 → 提交管理员审核
8. 对于已有文档/多维表格/知识库：需要将应用机器人添加为文档协作者（否则 API 无权访问）

### 常用场景所需权限

| 用户需求 | 需要申请的权限 | 额外要求 |
|----------|---------------|----------|
| 发送消息 | `im:message:send_as_bot` | 开启机器人能力 |
| 读写文档 | `docx:document` | 机器人需为文档协作者 |
| Markdown 转文档 | `docx:document` + `docx:document.block:convert` | — |
| 读写多维表格 | `bitable:app` | 机器人需为表格协作者 |
| 管理知识库 | `wiki:wiki` | 机器人需为知识空间成员 |
| 文件上传下载 | `drive:drive` | — |
| 文档权限管理 | `drive:permission` | — |
| 日历日程 | `calendar:calendar` | — |
| 审批流操作 | `approval:approval` + `approval:task` | — |
| 查询通讯录 | `contact:contact.base:readonly` | 配置通讯录权限范围 |
| 查询考勤 | `attendance:task:readonly` | 配置通讯录权限范围 |
| 事件订阅 | 对应事件的订阅权限 | 需在开发者后台配置「使用长连接接收事件/回调」 |
| 卡片交互回调 | `card:action.trigger` | 开启长连接订阅方式，订阅 card.action.trigger 回调 |

### 飞书应用信息持久化

引导用户完成应用配置后，将 App ID 和项目的飞书用途写入 `agent.md`，供后续会话判断是否需要重新引导：

```markdown
## 飞书集成

- **App ID**: cli_xxxxxxxxxxxxxxxx
- **用途**: 通过飞书 API 实现消息通知、文档自动生成（描述项目实际使用飞书做了什么）
```

## NestJS 模块设置

### 安装 SDK

```bash
npm install @larksuiteoapi/node-sdk
```

### FeishuService 单例

> ⚠️ **凭证写入源码**：全栈框架不支持自定义环境变量，因此 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 必须直接写在源码常量中，**不要改为 `process.env`**。

```typescript
import { Injectable } from '@nestjs/common';
import * as lark from '@larksuiteoapi/node-sdk';

const FEISHU_APP_ID = 'cli_xxxx';      // ← 用户提供的真实值
const FEISHU_APP_SECRET = 'xxxx';      // ← 用户提供的真实值

@Injectable()
export class FeishuService {
  private readonly client: lark.Client;

  constructor() {
    this.client = new lark.Client({
      appId: FEISHU_APP_ID,
      appSecret: FEISHU_APP_SECRET,
      appType: lark.AppType.SelfBuild,
      domain: lark.Domain.Feishu,
    });
  }

  getClient(): lark.Client {
    return this.client;
  }
}
```

在 Module 中注册为全局 provider：

```typescript
@Module({
  providers: [FeishuService],
  exports: [FeishuService],
})
export class FeishuModule {}
```

## 核心 API 调用模式

### 语义化调用

```typescript
// 调用模式: client.<domain>.<resource>.<method>({ params, data, path })
const res = await client.im.message.create({
  params: { receive_id_type: 'chat_id' },
  data: {
    receive_id: 'oc_xxx',
    content: JSON.stringify({ text: 'hello' }),
    msg_type: 'text',
  },
});

// 检查返回值
if (res.code !== 0) {
  throw new Error(`Feishu API error [${res.code}]: ${res.msg}`);
}
```

### 分页迭代器

接口名后缀加 `WithIterator` 自动处理 page_token：

```typescript
for await (const items of await client.contact.user.listWithIterator({
  params: { department_id: '0', page_size: 50 },
})) {
  console.log(items);
}
```

## 错误处理与权限诊断

### 常见错误码

| 错误码 | 含义 | 修复方法 |
|--------|------|----------|
| 99991672 | 权限不足 | 开发者后台 → 权限管理 → 申请对应权限 |
| 99991671 | access_token 无效/过期 | 检查 app_id/app_secret 是否正确 |
| 99991663 | tenant_access_token 过期 | SDK 自动刷新，检查网络连接 |
| 230001 | 应用不可见/未安装 | 管理员审核发布应用 |
| 99991400 | 参数错误 | 检查必填字段和参数类型 |
| 99991668 | 用户不在通讯录权限范围 | 安全设置 → 通讯录权限范围设为「全部成员」 |

### 权限速查

遇到 `99991672 Permission denied` 时，根据 API 域查找所需权限：

| API 域 | 权限标识 | 说明 |
|--------|----------|------|
| `im.message.*` | `im:message:send_as_bot` | 发送消息 |
| `calendar.calendarEvent.*` | `calendar:calendar` | 日历日程读写 |
| `vc.room.*` | `vc:room:readonly` | 会议室查询 |
| `approval.approval.*` | `approval:approval` | 审批信息读写 |
| `approval.instance.query` | `approval:approval.list:readonly` | 审批实例列表 |
| `approval.task.*` | `approval:task` | 审批操作（同意/拒绝/转交） |
| `bitable.app*` | `bitable:app` | 多维表格读写 |
| `docx.document.*` | `docx:document` | 云文档读写 |
| `docx.document.convert()` | `docx:document.block:convert` | Markdown 转 Block |
| `drive.*` | `drive:drive` | 云空间文件/文件夹 |
| `wiki.space.*` / `wiki.spaceNode.*` | `wiki:wiki` | 知识库读写 |
| `drive.permissionMember.*` | `drive:permission` | 文档权限管理 |
| `contact.user.*` | `contact:contact.base:readonly` | 通讯录用户信息 |
| `contact.department.*` | `contact:department.base:readonly` | 部门信息 |
| `contact.user.*.employee_id` | `contact:user.employee_id:readonly` | 用户 employee_id |
| `attendance.userTask.*` | `attendance:task:readonly` | 打卡数据 |
| `attendance.group.*` | `attendance:rule:readonly` | 考勤规则 |

## Common Mistakes

| 错误 | 正确做法 |
|------|----------|
| 将凭证改为 process.env 读取 | 全栈框架不支持自定义环境变量，凭证必须写入源码常量 |
| `content` 传对象而非 JSON 字符串 | `content: JSON.stringify({ text: 'hello' })` |
| 每次请求都新建 `lark.Client` | NestJS `@Injectable()` 单例模式复用 |
| `receive_id_type` 与 ID 前缀不匹配 | `oc_` → `chat_id`, `ou_` → `open_id`, `on_` → `union_id` |
| 未配置通讯录权限范围 | 安全设置 → 通讯录权限范围 → 全部成员 |
| 应用未发布直接调 API | 创建版本 → 管理员审核 → 发布后才能使用 |
| 忘记开启机器人能力 | 应用能力 → 添加机器人（发消息必须） |
| 日期格式搞混 | 日历用 RFC3339 (`2026-01-01T09:00:00+08:00`)，考勤用整数 (`20260101`) |
| 生成独立可运行的脚本文件 | 所有飞书调用放在 NestJS Service 方法中，由 Controller 调用 |

