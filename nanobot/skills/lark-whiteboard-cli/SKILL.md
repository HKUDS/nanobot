---
name: lark-whiteboard-cli
description: >
  当用户要求或使用飞书画板绘制架构图、流程图、思维导图、时序图或其他可视化图表时使用此 skill，作为使用 whiteboard-cli 设计图表布局的指南
compatibility: Requires Node.js 18+
metadata:
  requires:
    bins: ["lark-cli"]
---

> [!NOTE]
> **环境依赖**：绘制画板需要 `@larksuite/whiteboard-cli`（画板 Node.js CLI 工具），以及 `lark-cli`（LarkSuite CLI 工具）。
> 如果执行失败，手动安装后重试：`npm install -g @larksuite/whiteboard-cli@^0.2.0`

> [!IMPORTANT]
> 执行 `npm install` 安装新的依赖前，务必征得用户同意！


## Workflow

> **这是画板，不是网页。** 画板是无限画布上自由放置元素，flex 布局是可选增强。

```
Step 1: 路由 & 读取知识
  - 判断渲染路径（见路由表）：Mermaid 还是 DSL？
  - 读对应 scene 指南 — 了解结构特征和布局策略
  - 确定布局策略（见下方快速判断）和构建方式
  - 读 references/ 核心模块 — 语法、布局、配色、排版、连线

Step 2: 生成完整 DSL（含颜色）
  - 按 content.md 规划信息量和分组
  - 按 layout.md 选择布局模式和间距
  - 推荐使用图标让图表更直观，运行 `npx -y @larksuite/whiteboard-cli@^0.2.0 --icons` 查看可用图标，选取合适的图标, 但不要过度使用或者所有图表都用图标, 根据图表类型和内容选择是否使用图标
  - 按 style.md 上色（用户没指定时用默认经典色板）
  - 按 schema.md 语法输出完整 JSON
  - 连线参考 connectors.md，排版参考 typography.md

  注意：部分图形（鱼骨/飞轮/柱状/折线等）要按 scene 指南的脚本模板写 .js 脚本生成 JSON：
    1. 创建产物目录 ./diagrams/YYYY-MM-DDTHHMMSS/
    2. 将脚本保存为 diagram.gen.js，执行 node diagram.gen.js 产出 diagram.json
    3. 用产出的 diagram.json 进入 Step 3

Step 3: 渲染 & 审查 → 交付
  - 渲染前自查（见下方检查清单）
  - 渲染 PNG，检查：
    · 信息完整？布局合理？配色协调？
    · 文字无截断？连线无交叉？
  - 有问题 → 按症状表修复 → 重新渲染（最多 2 轮）
  - 2 轮后仍有严重问题 → 考虑走 Mermaid 路径兜底
  - 没问题 → 交付：
    · 用户要求上传飞书 → 见下方”上传飞书画板”章节中的说明
    · 用户未指定 → 展示 PNG 图片给用户
```

**布局策略快速判断**（详见 `references/layout.md`）：

先定**主布局**，再定子布局：**结构化信息**优先用 Flex，**关系链路**优先用 Dagre，**灵活定位**用绝对布局。

涉及 Dagre / Flex 的具体边界、危险模式、混合布局原则，统一以 `references/layout.md` 为准；scene 文件只描述场景差异，不重复定义通用布局规则。

> **构建方式是强约束**：当 scene 指南要求"脚本生成"时，必须先写脚本（.js）并用 `node` 执行来产出 JSON 文件。绝对定位场景（鱼骨图、飞轮图、柱状图、折线图等）的坐标需要数学计算，直接手写 JSON 极易导致节点重叠或连线穿模。
---

## 渲染路径选择（DSL or Mermaid）

| 图表类型     | 路径        | 理由                |
| ------------ | ----------- | ------------------- |
| 思维导图     | **Mermaid** | 辐射结构自动布局    |
| 时序图       | **Mermaid** | 参与方+消息自动排列 |
| 类图         | **Mermaid** | 类关系自动布局      |
| 饼图         | **Mermaid** | Mermaid 原生支持    |
| 其他所有类型 | **DSL**     | 精确控制样式和布局  |

**路由规则**：
1. **自动 Mermaid**：思维导图、时序图、类图、饼图 → 默认走 Mermaid
2. **显式 Mermaid**：用户输入包含 Mermaid 语法 → 走 Mermaid
3. **DSL 路径**：其他所有类型 → 先读核心模块，再读对应场景指南

**Mermaid 路径**：参考 `scenes/mermaid.md` 编写 `.mmd` 文件，跳过 DSL 模块。
**DSL 路径**：按 Workflow 3 步执行。

---

## 模块索引

### 核心参考（DSL 路径必读）

| 模块     | 文件                       | 说明                            |
| -------- | -------------------------- | ------------------------------- |
| DSL 语法 | `references/schema.md`     | 节点类型、属性、尺寸值          |
| 内容规划 | `references/content.md`    | 信息提取、密度决策、连线预判    |
| 布局系统 | `references/layout.md`     | 网格方法论、Flex 映射、间距规则 |
| 排版规则 | `references/typography.md` | 字号层级、对齐、行距            |
| 连线系统 | `references/connectors.md` | 拓扑规划、锚点选择              |
| 配色系统 | `references/style.md`      | 多色板、视觉层级                |


### 场景指南（按类型选读一个）

| 图表类型    | 文件                     | 适用场景                               |
| ----------- | ------------------------ | -------------------------------------- |
| 架构图      | `scenes/architecture.md` | 分层架构、微服务架构                   |
| 组织架构图  | `scenes/organization.md` | 公司组织、树形层级                     |
| 泳道图      | `scenes/swimlane.md`     | 跨角色流程、跨系统交互流程、端到端链路 |
| 对比图      | `scenes/comparison.md`   | 方案对比、功能矩阵                     |
| 鱼骨图      | `scenes/fishbone.md`     | 因果分析、根因分析                     |
| 柱状图      | `scenes/bar-chart.md`    | 柱状图、条形图                         |
| 折线图      | `scenes/line-chart.md`   | 折线图、趋势图                         |
| 树状图      | `scenes/treemap.md`      | 矩形树图、层级占比                     |
| 漏斗图      | `scenes/funnel.md`       | 转化漏斗、销售漏斗                     |
| 金字塔图    | `scenes/pyramid.md`      | 层级结构、需求层次                     |
| 循环/飞轮图 | `scenes/flywheel.md`     | 增长飞轮、闭环链路                     |
| 里程碑      | `scenes/milestone.md`    | 时间线、版本演进                       |
| 流程图      | `scenes/flowchart.md`    | 业务流、状态机、带条件判断的链路       |
| Mermaid     | `scenes/mermaid.md`      | 思维导图、时序图、类图、饼图           |

---

## 文件产物规范

每次绘图在 `./diagrams/` 下按当前时间创建子目录（格式 `YYYY-MM-DDTHHMMSS`），目录内文件名固定。用户指定了保存路径时以用户为准。

```
./diagrams/
  2026-03-27T143000/      ← 自动按时间创建，无需起名
    diagram.json          ← DSL（CLI 输入）
    diagram.gen.js        ← 坐标计算脚本（仅脚本构建方式）
    diagram.png           ← 最终图片
    diagram.mmd           ← Mermaid 源码（仅 Mermaid 路径）
```

## CLI 命令

**查看可用图标**：
```bash
npx -y @larksuite/whiteboard-cli@^0.2.0 --icons
```

**渲染**：
```bash
npx -y @larksuite/whiteboard-cli@^0.2.0 -i ./diagrams/2026-03-27T143000/diagram.json -o ./diagrams/2026-03-27T143000/diagram.png    # DSL
npx -y @larksuite/whiteboard-cli@^0.2.0 -i ./diagrams/2026-03-27T143000/diagram.mmd -o ./diagrams/2026-03-27T143000/diagram.png     # Mermaid
```

**上传飞书画板**：

> 上传需要飞书认证。遇到认证或权限错误时，阅读 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md) 了解登录和权限处理。

**第一步：获取画板 Token**

| 用户给了什么                       | 怎么获取 Token                                                                                                                                                 |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 画板 Token（`XXX`）                | 直接使用                                                                                                                                                       |
| 文档 URL 或 doc_id，文档中已有画板 | `lark-cli docs +fetch --doc <URL> --as user`，从返回的 `<whiteboard token=”XXX”/>` 中提取 token                                                                |
| 文档 URL 或 doc_id，需要新建画板   | `lark-cli docs +update --doc <doc_id> --mode append --markdown '<whiteboard type=”blank”></whiteboard>' --as user`，从响应的 `data.board_tokens[0]` 获取 token |

关于飞书文档的创建，读取等更多操作，请参考 lark-doc skill [`../lark-doc/SKILL.md`](../lark-doc/SKILL.md)。

**第二步：上传**

> [!CAUTION]
> **MANDATORY PRE-FLIGHT CHECK (上传前强制拦截检查)**
> 当你要向一个**已存在的画板 Token** 写入内容时，**绝对禁止**直接执行上传命令！你必须严格遵守以下两步：
> **强制执行 Dry Run（状态探测）**
> 必须先在命令中添加 `--overwrite --dry-run` 参数来探测画板当前状态。示例命令：
> ```bash
> npx -y @larksuite/whiteboard-cli@^0.2.0 --to openapi -i <输入文件> --format json | lark-cli whiteboard +update --whiteboard-token <Token> --source - --overwrite --dry-run --as user
> ```
>
> **解析结果并拦截**
> - 仔细阅读 Dry Run 的输出日志。
> - **如果日志包含 `XX whiteboard nodes will be deleted`**：这说明画板**非空**，当前操作会覆盖并摧毁用户的原有图表！
> - **你必须立即停止操作**，并通过 `AskUserQuestion` 工具（或直接回复）向用户确认：”目标画板当前非空，继续更新将清空原有的 XX 个节点，是否确认覆盖？”
> - 只有在用户明确授权”同意覆盖”后，你才能移除 `--dry-run` 真正执行上传。
> - 用户可能会要求你不覆盖更新画板内容，在这种情况下，移除 `--overwrite` 和 `--dry-run` 参数再上传。

```bash
npx -y @larksuite/whiteboard-cli@^0.2.0 --to openapi -i <输入文件> --format json | lark-cli whiteboard +update --whiteboard-token <画板Token> --source - --yes --as user
```
> 画板一经上传不可修改。如需应用身份上传，将 `--as user` 替换为 `--as bot`。
> 如果画板非空，先加 `--overwrite --dry-run` 检查待删除节点数，向用户确认后去掉 `--dry-run` 执行。

你也可以将布局输出为原生 OpenAPI json 格式，再通过 lark-cli 导入飞书画板。关于 lark-cli 操作画板的更多方式，请参照 [../lark-whiteboard/SKILL.md](../lark-whiteboard/SKILL.md)

**症状→修复表**（视觉审查发现问题时参照）：

| 看到的问题         | 改什么                              |
| ------------------ | ----------------------------------- |
| 文字被截断         | height 改为 fit-content             |
| 文字溢出容器右侧   | 增大 width，或缩短文字              |
| 节点重叠粘连       | 增大 gap                            |
| 节点挤成一团       | 增大 padding 和 gap                 |
| 连线穿过节点       | 调整 fromAnchor/toAnchor 或增大间距 |
| 大面积空白         | 缩小外层 frame 宽度                 |
| 文字和背景色太接近 | 调整 fillColor 或 textColor         |
| 布局整体偏左/偏右  | 调整绝对定位的 x 坐标使内容居中     |

---

## 渲染前自查

生成 DSL 后、渲染前，快速检查：

- [ ] 不同分组用了不同颜色？同组节点样式完全一致？
- [ ] 外层浅色背景、内层白色节点？（外重内轻）
- [ ] 所有节点有边框（borderWidth=2）？文字在背景上清晰可读？
- [ ] 连线用灰色（#BBBFC4），不用彩色？
- [ ] frame 都写了 layout 属性？gap 和 padding 都显式设置了？
- [ ] 含文字节点 height 用 fit-content？connector 在顶层 nodes 数组？

---

## 关键约束速查

> 最高频出错的规则，即使不读子模块文件也必须遵守。

1. **含文字节点的 height 必须用 `'fit-content'`** — 写死数值会截断文字
2. **`fill-container` 仅在 flex 父容器中生效** — `layout: 'none'` 下宽度退化为 0
3. **`layout: 'none'` 的容器必须有固定宽高** — 不要写成 `fit-content`
4. **connector 必须放在顶层 nodes 数组** — 不能嵌套在 frame children 里
5. **图层顺序** — 数组顺序 = 绘制顺序。后定义的元素层级越高，会覆盖先定义的。重叠/浮层/标注元素务必放在数组末尾。
6. **flex 容器内的 x/y 会被完全忽略** — 需要自由定位时用 `layout: 'none'` 或放在顶层 nodes
7. **Dagre 子容器默认为不透明节点** — 外层连线无法寻址其内部子节点（引擎会自动重定向至外壳）。需穿透时声明 `layout: "dagre"` + `layoutOptions: { isCluster: true }`

❌ 致命错误：flex 容器内设 x/y，坐标不生效，节点按顺序排列
```json
{ "type": "frame", "layout": "vertical", "children": [
  { "type": "rect", "x": 100, "y": 0, "text": "成都" },
  { "type": "rect", "x": 540, "y": 0, "text": "康定" }
]}
```
✅ 正确：用 `layout: "none"` 或放在顶层 nodes 用 x/y 定位。

❌ 致命错误：`layout: "none"` 容器本身写 `width: "fit-content", height: "fit-content"`，再在内部摆绝对坐标节点

✅ 正确：绝对定位容器先给固定宽高，再在内部用 x/y 放置子节点。
