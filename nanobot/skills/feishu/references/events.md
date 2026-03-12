# 事件订阅 (Events)

通过 WebSocket 长连接接收飞书事件推送，无需公网 IP / 域名，无需加解密。

## WebSocket 长连接（推荐）

使用 NestJS `OnModuleInit` 生命周期钩子启动 WebSocket 长连接：

```typescript
import { Injectable, OnModuleInit } from '@nestjs/common';
import * as lark from '@larksuiteoapi/node-sdk';

@Injectable()
export class FeishuEventService implements OnModuleInit {
  private readonly wsClient: lark.WSClient;

  constructor(private readonly feishuService: FeishuService) {
    const client = this.feishuService.getClient();
    this.wsClient = new lark.WSClient({
      appId: FEISHU_APP_ID,
      appSecret: FEISHU_APP_SECRET,
      loggerLevel: lark.LoggerLevel.info,
    });
  }

  onModuleInit() {
    this.wsClient.start({
      eventDispatcher: new lark.EventDispatcher({}).register({
        'im.message.receive_v1': async (data) => {
          // 处理收到的消息事件
        },
      }),
    });
  }
}
```

## 消息卡片回调（card.action.trigger）

用户点击卡片按钮、选择下拉项等交互操作会触发 `card.action.trigger` 回调，通过长连接接收，在 `EventDispatcher.register()` 中注册处理函数即可。

> **前置配置**：开发者后台 → 事件与回调 → 订阅方式 → 选择「**使用长连接接收事件/回调**」（而非 HTTP 回调地址）

```typescript
import { Injectable, OnModuleInit } from '@nestjs/common';
import * as lark from '@larksuiteoapi/node-sdk';

@Injectable()
export class FeishuEventService implements OnModuleInit {
  private readonly wsClient: lark.WSClient;

  constructor(private readonly feishuService: FeishuService) {
    this.wsClient = new lark.WSClient({
      appId: FEISHU_APP_ID,
      appSecret: FEISHU_APP_SECRET,
      loggerLevel: lark.LoggerLevel.info,
    });
  }

  onModuleInit() {
    this.wsClient.start({
      eventDispatcher: new lark.EventDispatcher({}).register({
        // 普通消息事件
        'im.message.receive_v1': async (data) => {
          // 处理收到的消息事件
        },

        // 消息卡片交互回调
        'card.action.trigger': async (data) => {
          const {
            action,    // 用户触发的交互动作
            operator,  // 操作者信息
            context,   // 卡片上下文
          } = data;

          // action.value      — 交互元素配置的 value（JSON 对象）
          // action.tag        — 触发的组件类型：'button' | 'select_static' | 'date_picker' 等
          // action.option     — 下拉选框选中的值（select_static 专用）
          // action.form_value — 表单容器提交数据（Record<string, string | string[]>）
          // action.name       — 用户操作的交互组件名称（开发者自定义）
          // operator.open_id  — 操作者 open_id（直接字段，非嵌套）
          // operator.user_id  — 操作者 user_id（字符串）
          // operator.union_id — 操作者 union_id
          // context.open_message_id   — 卡片消息 ID（可用于 patch 更新）
          // context.open_chat_id      — 所在会话 ID

          // 返回新卡片内容可直接更新该卡片（返回 undefined 则不更新）
          // 响应体为 v2 格式：{ toast?, card: { type: 'raw', data: { schema: '2.0', ... } } }
          if (action.value?.confirm) {
            return {
              toast: {
                type: 'success',
                content: '操作已完成',
                i18n: { zh_cn: '操作已完成', en_us: 'Done' },
              },
              card: {
                type: 'raw',
                data: {
                  schema: '2.0',
                  config: { update_multi: true },
                  header: {
                    template: 'green',
                    title: { content: '已确认', tag: 'plain_text' },
                  },
                  body: {
                    direction: 'vertical',
                    elements: [
                      { tag: 'markdown', content: '操作已完成 ✅' },
                    ],
                  },
                },
              },
            };
          }
        },
      }),
    });
  }
}
```

### card.action.trigger 事件数据结构

长连接模式下事件为 v2 格式，`EventDispatcher` 解析后将 `header` 和 `event` 字段平铺到 `data` 中：

| 字段 | 类型 | 说明 |
|------|------|------|
| `action.value` | `Record<string, any>` | 交互元素配置的 value 数据 |
| `action.tag` | `string` | 组件类型：`button` / `select_static` / `date_picker` 等 |
| `action.option` | `string?` | 下拉选框选中项（select_static 触发时有值） |
| `action.timezone` | `string?` | 时区（日期选择器触发时有值） |
| `action.form_value` | `Record<string, string \| string[]>?` | 表单容器提交数据（form 组件触发时有值） |
| `action.name` | `string?` | 用户操作的交互组件名称（开发者在组件上自定义） |
| `operator.open_id` | `string` | 操作者 open_id（直接字段，非嵌套） |
| `operator.user_id` | `string?` | 操作者 user_id |
| `operator.union_id` | `string?` | 操作者 union_id |
| `operator.tenant_key` | `string?` | 操作者所在租户 key |
| `context.open_message_id` | `string` | 卡片所在消息 ID |
| `context.open_chat_id` | `string` | 卡片所在会话 ID |
| `token` | `string` | 回调 token（验签用，长连接模式无需手动验签） |
| `host` | `string` | 宿主环境，如 `im_message` |

### card.action.trigger 响应体结构（v2 格式）

处理函数 return 的对象会作为响应体直接更新卡片，必须使用 v2 格式：

```json
{
  "toast": {
    "type": "info",
    "content": "提示内容",
    "i18n": { "zh_cn": "提示内容", "en_us": "Message" }
  },
  "card": {
    "type": "raw",
    "data": {
      "schema": "2.0",
      "config": { "update_multi": true },
      "header": {
        "title": { "tag": "plain_text", "content": "标题" },
        "template": "blue"
      },
      "body": {
        "direction": "vertical",
        "elements": [
          { "tag": "markdown", "content": "卡片内容" }
        ]
      }
    }
  }
}
```

| 字段 | 必需 | 说明 |
|------|------|------|
| `toast` | 否 | 在用户侧显示浮层提示；`type` 可选 `info` / `success` / `error` / `warning` |
| `card` | 否 | 更新后的卡片内容；不返回则卡片保持不变 |
| `card.type` | 是 | 固定为 `"raw"` |
| `card.data.schema` | 是 | 固定为 `"2.0"` |
| `card.data.body.elements` | 是 | 卡片元素列表（嵌套在 `body` 中，非根级） |

> **与旧版区别**：v1 格式直接在根级放 `elements`；v2 格式必须将元素放在 `card.data.body.elements` 中，且外层需要 `card.type: "raw"` 包装。

### 卡片更新方式对比

| 方式 | 说明 |
|------|------|
| 处理函数直接 return 卡片 | 即时更新触发交互的卡片（推荐，3 秒内处理完成） |
| `client.im.message.patch()` | 异步更新，适合耗时操作（需在另一协程/队列中处理） |

## 当前不支持

以下模式需要飞书通过 HTTP 回调应用服务，当前环境暂不支持：

- Webhook 事件订阅（HTTP 模式）— 使用上方 WebSocket 长连接代替
- HTTP 模式 CardActionHandler — 使用长连接 `card.action.trigger` 代替（见上方）
