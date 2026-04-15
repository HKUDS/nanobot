# 泳道图（Swimlane）

适用于：跨角色/跨系统的端到端流程（用户/网关/服务/存储/回调）、多泳道协作流程、系统交互链路图。

支持两种方向：
- **水平泳道**：泳道为横向条带（自上而下排列），流程从左到右推进
- **垂直泳道**：泳道为纵向列（自左向右排列），流程从上到下推进

## Content 约束

- 泳道数（lanes）建议 3-7，超过 7 会显著降低可读性；如必须更多泳道，优先合并同类或拆成两张图
- 阶段数（stages）建议 4-8；超过 8 优先合并相邻阶段或改成“代表性阶段”
- 每个阶段在每条泳道中最多放 1 个“主步骤卡片”；如同一阶段需要多个步骤，放在同一格内做纵向堆叠（2-3 个为上限）
- 节点文本 1-2 行为主；长文本用 `\n` 手动换行，避免单行超长导致卡片过宽
- 仅画必要连线：泳道图的结构已经表达了“属于哪个角色/系统 + 发生顺序”，连线只用于表达跨泳道交互、关键因果关系或异步事件流

## Layout 选型

| 模式 | 适用条件 | 特征 |
|------|---------|------|
| **水平泳道** | 默认推荐；流程天然左→右推进 | lanes=行，stages=列；跨泳道同一阶段严格 x 对齐 |
| **垂直泳道** | 用户明确要求竖版、或画布更适合纵向滚动阅读 | lanes=列，stages=行；跨泳道同一阶段严格 y 对齐 |

## Layout 规则

### 通用规则（两种方向都适用）

1. **网格对齐是第一优先级**：跨泳道同一阶段必须严格对齐（水平对齐 x；垂直对齐 y）。对齐通过“共享阶段标尺（stage ruler / stage slots）”实现，不靠肉眼估算，也不靠逐节点随意手写坐标
2. **只生成真实节点**：为保证跨泳道阶段严格对齐，所有阶段统一保留透明的 **stage cell**；仅在真实阶段的 cell 内生成卡片节点，并按阶段索引映射到对应槽位
3. **泳道容器禁止使用背景色**：每条泳道是一个可见的分组容器，只能使用边框表达分组（建议统一使用浅灰色细虚线 `borderDash: "dashed"`，`borderWidth: 1`，`borderColor: "#DEE0E3"`），**不得使用任何有色背景作为泳道底色**，以降低视觉噪音。必须显式声明 `fillColor: "transparent"`，保持视觉透明
4. **步骤卡片**：使用 `rect`。为建立清晰的视觉层级，卡片**必须填充浅色背景**（参考 `references/style.md` 中的浅色板，如极浅的主题色），边框使用对应的主题主色（`borderWidth: 1-2`），文字使用深色（如 `#1F2329`）以确保可读性。统一圆角；宽高以可读为先，避免过窄导致换行过多
5. **间距**：只要存在 connector 连线，卡片之间的主轴间距必须满足 `gap >= 40`；如果连线包含文字（`label`），主轴间距必须 `gap >= 64`，以提供充足的阅读空间。

### 子节点对齐

- **同一阶段必须严格对齐**：所有泳道复用同一套 stage slots；不允许靠卡片自身宽度或肉眼估算来对齐
- **卡片宽度一致**：同一泳道中的步骤卡片应保持统一宽度；推荐使用统一固定宽度，或严格复用同一槽位宽度
- **统一使用 stack 容器**：有内容的阶段统一使用 `layout: "vertical"` 的 stack frame（纵向堆叠 1-3 张卡片）；空阶段不生成 stack/卡片，但保留透明 cell 保证对齐
- **垂直居中但不影响对齐**：stage cell 默认 `alignItems: "stretch"`，可用 `justifyContent: "center"` 让卡片在 cell 内居中，以确保左右边界严格对齐
- **不靠底色区分行/列**：阶段网格默认不需要背景色；如需“轻微”的行/列边界提示，优先给 stage cell 加 1px 细边框（`fillColor: "transparent"` 仍保持视觉透明）

### Flex 栅格模式（默认）

- lane body 使用 Flex 布局：水平泳道用 `layout: "horizontal"`，垂直泳道用 `layout: "vertical"`
- 为每个阶段生成一个 **stage cell**（占位单元格）；空阶段的 cell 透明但保留；cell 内用 `layout: "vertical"` 的 stack 承载 1-3 张卡片
- 统一参数：`slotWidth: 180-220`（水平泳道 cell 宽度）、`slotHeight: 64-104`（垂直泳道 cell 高度建议档）、`gap: 40-56`（有连线时必须 ≥40）、`stackGap: 8`、`lanePadding: 16`
- 对齐规则：所有泳道复用同一组 `slotWidth/slotHeight/gap`；同一阶段在各泳道上使用相同的 cell 索引保证严格对齐
- 尺寸语义：lane body `width/height` 用 `"fit-content"`（Yoga 自适应）；卡片 `height: "fit-content"`；Flex 容器内不写子节点 `x/y`
- 内容密度：卡片文字 1-2 行；同阶段堆叠上限 2-3；超过上限优先拆分到相邻阶段或缩短文本

### 跨泳道间距（lanesGap）

- 根容器承载所有泳道：水平泳道用 `layout: "vertical"`，垂直泳道用 `layout: "horizontal"`
- 固定跨泳道主轴间距 `lanesGap`（建议 `64-80`），更宽的间距能让跨泳道连线（特别是带文字时）有更多留白，降低重叠感
- 每条泳道作为根容器的子 frame，内部再使用上述 Flex 栅格的 stage cell 布局
- `lanesGap` 与 `lanePadding/stackGap` 独立；lane 内容增减不应影响跨泳道间距
- 4px 基线对齐：`lanesGap`、`lanePadding`、cell 尺寸建议按 4 的倍数对齐

### 水平泳道（lanes=行，stages=列）

- 根容器：`layout: "vertical"`，`gap: lanesGap` 固定；`alignItems: "stretch"`，标题在最上方
- 每条泳道：一个可见 frame（分组容器），内部用 `layout: "horizontal"` 分成两块：
  - 左侧 lane label：固定宽度 text（如 100-140），垂直居中；左对齐（`textAlign: "left"`）；title 需要比步骤卡片更醒目，优先通过 `fontSize: 18-20` + `fontWeight: "bold"` + 与泳道边框一致的 `textColor` 实现
  - 右侧 lane body：`layout: "horizontal"`，包含完整的阶段 **stage cell** 数组；cell 宽度固定为 `slotWidth`，相邻 cell 间 `gap` 统一；空阶段 cell 透明但保留
- 步骤卡片：推荐统一卡片宽度（如 160-220），并在所有泳道复用同一组 `slotWidth / gap`，保证跨泳道阶段严格 x 对齐

### 垂直泳道（lanes=列，stages=行）

- 根容器：`layout: "horizontal"`，`gap: lanesGap` 固定；`alignItems: "stretch"`，标题在最上方
- 每条泳道：一个可见 frame（分组容器），内部 `layout: "vertical"`：
  - 顶部 lane label：必须放在单独的 `lane label frame` 中，label frame 使用 `width: "fill-container"`、`alignItems: "center"`、`justifyContent: "center"`，并通过 `paddingTop` 留出与泳道上边的 gap（推荐 `12-16`，按 4px 基线取值，如 `padding: [12, 8, 8, 8]`）；内部 text 使用 `width: "fill-container"` + `textAlign: "center"`，确保 title 在整条泳道顶部**水平居中**
  - lane body：`layout: "vertical"`，包含完整的阶段 **stage cell** 数组；cell 高度固定为 `slotHeight`，相邻 cell 间 `gap` 统一；空阶段 cell 透明但保留
  - 内容居中对齐：stage cell 建议 `alignItems: "center"` + `justifyContent: "center"`，让卡片在每个 cell 内水平/垂直居中；卡片宽度不超过 `slotWidth`（或固定宽度），避免被 `"fill-container"` 拉伸导致“看起来不居中”
- 步骤卡片：推荐统一卡片高度或统一 `slotHeight / gap`，保证跨泳道阶段严格 y 对齐
- 泳道外层容器必须显式写 `fillColor: "transparent"`、`borderDash: "dashed"`、`borderWidth: 1`、`borderColor: "#DEE0E3"`（统一浅灰色），否则会被编译为虚拟 frame 导致不渲染
- 统一高度（Flex 自适应，可选）：根容器使用 `alignItems: "stretch"`，每个泳道外层 frame 使用 `height: "fill-container"`；泳道内部仍保持 lane label + lane body 的结构

示例：

```json
{
  "version": 2,
  "nodes": [
    {
      "type": "frame",
      "id": "lanes-root",
      "x": 40, "y": 40,
      "layout": "horizontal",
      "gap": 64,
      "alignItems": "stretch",
      "children": [
        {
          "type": "frame",
          "id": "lane-left",
          "layout": "vertical",
          "width": "fit-content",
          "height": "fill-container",
          "fillColor": "transparent",
          "borderDash": "dashed",
          "borderWidth": 1,
          "borderColor": "#DEE0E3",
          "children": [
            { "type": "frame", "id": "lane-left-label-wrap", "layout": "vertical", "width": "fill-container", "height": "fit-content",
              "alignItems": "center", "justifyContent": "center", "padding": [12, 8, 8, 8], "children": [
                { "type": "text", "id": "lane-left-label", "text": "Lane Left", "width": "fill-container", "height": "fit-content",
                  "textAlign": "center", "verticalAlign": "middle", "fontSize": 18, "fontWeight": "bold", "textColor": "#5178C6" }
              ] },
            { "type": "frame", "id": "lane-left-body", "layout": "vertical",
              "gap": 64, "padding": 16,
              "children": [
                { "type": "frame", "id": "stage-1-cell-left", "layout": "vertical", "width": 220, "height": 80, "alignItems": "center", "justifyContent": "center",
                  "children": [{ "type": "rect", "id": "c-s1", "width": 200, "height": "fit-content", "fillColor": "#E1EAFA", "borderColor": "#5178C6", "borderWidth": 2, "borderRadius": 8 }] },
                { "type": "frame", "id": "stage-2-cell-left", "layout": "vertical", "width": 220, "height": 80, "alignItems": "center", "justifyContent": "center", "children": [] }
              ] }
          ]
        },
        {
          "type": "frame",
          "id": "lane-right",
          "layout": "vertical",
          "width": "fit-content",
          "height": "fill-container",
          "fillColor": "transparent",
          "borderDash": "dashed",
          "borderWidth": 1,
          "borderColor": "#DEE0E3",
          "children": [
            { "type": "frame", "id": "lane-right-label-wrap", "layout": "vertical", "width": "fill-container", "height": "fit-content",
              "alignItems": "center", "justifyContent": "center", "padding": [12, 8, 8, 8], "children": [
                { "type": "text", "id": "lane-right-label", "text": "Lane Right", "width": "fill-container", "height": "fit-content",
                  "textAlign": "center", "verticalAlign": "middle", "fontSize": 18, "fontWeight": "bold", "textColor": "#8569CB" }
              ] },
            { "type": "frame", "id": "lane-right-body", "layout": "vertical",
              "gap": 64, "padding": 16,
              "children": [
                { "type": "frame", "id": "stage-1-cell-right", "layout": "vertical", "width": 220, "height": 80, "alignItems": "center", "justifyContent": "center", "children": [] },
                { "type": "frame", "id": "stage-2-cell-right", "layout": "vertical", "width": 220, "height": 80, "alignItems": "center", "justifyContent": "center",
                  "children": [{ "type": "rect", "id": "d-s2", "width": 200, "height": "fit-content", "fillColor": "#EAE6F3", "borderColor": "#8569CB", "borderWidth": 2, "borderRadius": 8 }] }
              ] }
          ]
        }
      ]
    },
    { "type": "connector", "connector": { "from": "c-s1", "to": "d-s2",
      "lineShape": "polyline", "lineColor": "#BBBFC4", "lineWidth": 2, "endArrow": "arrow" } }
  ]
}
```

### 泳道配色（默认色板）

- **泳道边框**：所有泳道外层容器统一使用浅灰色细虚线（`borderColor: "#DEE0E3"`, `borderWidth: 1`, `borderDash: "dashed"`）。
- **泳道标题**：按 `references/style.md` 经典色板为每条泳道分配不同的主题色，泳道 title 的 `textColor` 使用该主题色。
- **内容节点（rect）**：采用“浅色底 + 主题色边框”策略。`fillColor` 使用与该泳道主题色对应的极浅色（如浅蓝、浅紫等），`borderColor` 使用对应的主题色，文字 `textColor` 统一使用深色 `#1F2329`。
- **连线（connector）**：连线颜色固定为灰色 `#BBBFC4`，不随泳道颜色变化。当连线带有文字（`label`）时，为防止文字压在边框上难以阅读，必须为连线文字设置纯白背景（`labelFillColor: "#FFFFFF"`）遮挡底纹。

提醒：避免创建“虚拟 frame”（见 `references/schema.md` 的说明）。lane 外层必须具有可见属性以避免在编译时被跳过。


## 连线规则（强制参考 connectors.md）

泳道图中所有连线的选择与写法必须严格遵循 `references/connectors.md`，尤其是：
- `connector` 必须放在 `WBDocument.nodes` 顶层，不能嵌套在 `children`
- 默认优先使用自动绕线：`lineShape: "polyline"` / `"rightAngle"`，且不写 `waypoints`
- 未指定 `lineShape` 时默认使用 `"rightAngle"`
- 只有在必要时才强制锚点方向；锚点选择必须与节点相对位置一致
- 有连线时卡片间距必须满足 `gap >= 40`；如果连线包含文字（`label`），主轴间距必须 `gap >= 64`
- 带文字的连线必须设置 `labelFillColor: "#FFFFFF"` 遮挡底纹

泳道图语境下的落地约束：
- **默认不写锚点**，交给引擎自动推断；只有需要强制“左→右推进 / 上→下推进”时才写
- 需要表达“异步/事件流/推送”（如 SSE/Chunk）时：使用 `lineStyle: "dashed"` 并配合 `label` 说明语义；其他参数仍按 connectors.md
- 避免连接“仅用于布局且可能被优化掉的虚拟 frame”，尽量连接具体步骤卡片的节点 id（参考 `references/schema.md` 的虚拟 frame 陷阱）

## 骨架示例

> 示例展示布局的结构与对齐方法；实际节点的样式满足当前布局规则的前提下参考 `references/style.md`

- 水平泳道示例：

```json
{
  "version": 2,
  "nodes": [
    {
      "type": "frame",
      "id": "lanes-root",
      "x": 40,
      "y": 40,
      "layout": "vertical",
      "gap": 64,
      "alignItems": "stretch",
      "padding": 0,
      "width": "fit-content",
      "height": "fit-content",
      "children": [
        {
          "type": "frame",
          "id": "lane-a",
          "layout": "horizontal",
          "gap": 64,
          "padding": 16,
          "width": "fit-content",
          "height": "fill-container",
      "fillColor": "transparent",
      "borderDash": "dashed",
      "borderWidth": 1,
      "borderColor": "#DEE0E3",
          "children": [
        {
          "type": "text",
          "id": "lane-a-label",
          "text": "Lane A",
          "width": 120,
          "height": "fit-content",
          "textAlign": "left",
          "verticalAlign": "middle",
          "fontSize": 18,
          "fontWeight": "bold",
          "textColor": "#5178C6"
        },
        {
          "type": "frame",
          "id": "stage-1-cell-a",
          "layout": "vertical",
          "gap": 8,
          "padding": 0,
          "width": 200,
          "height": "fit-content",
          "fillColor": "transparent",
          "alignItems": "stretch",
          "justifyContent": "center",
          "children": [
                {
                  "type": "rect",
                  "id": "a-s1",
                  "width": "fill-container",
                  "height": "fit-content",
                  "fillColor": "#E1EAFA",
                  "borderColor": "#5178C6",
                  "borderWidth": 2,
                  "borderRadius": 8,
                  "text": "[阶段 1 节点]",
                  "fontSize": 14,
                  "textColor": "#1F2329",
                  "textAlign": "center",
                  "verticalAlign": "middle"
                }
              ]
            },
        {
          "type": "frame",
          "id": "stage-2-cell-a",
          "layout": "vertical",
          "gap": 8,
          "padding": 0,
          "width": 200,
          "height": "fit-content",
          "fillColor": "transparent",
          "alignItems": "stretch",
          "justifyContent": "center",
          "children": []
        }
          ]
        },
        {
          "type": "frame",
          "id": "lane-b",
          "layout": "horizontal",
          "gap": 64,
          "padding": 16,
          "width": "fit-content",
          "height": "fill-container",
      "fillColor": "transparent",
      "borderDash": "dashed",
      "borderWidth": 1,
      "borderColor": "#DEE0E3",
          "children": [
        {
          "type": "text",
          "id": "lane-b-label",
          "text": "Lane B",
          "width": 120,
          "height": "fit-content",
          "textAlign": "left",
          "verticalAlign": "middle",
          "fontSize": 18,
          "fontWeight": "bold",
          "textColor": "#8569CB"
        },
        {
          "type": "frame",
          "id": "stage-1-cell-b",
          "layout": "vertical",
          "gap": 8,
          "padding": 0,
          "width": 200,
          "height": "fit-content",
          "fillColor": "transparent",
          "alignItems": "stretch",
          "justifyContent": "center",
          "children": []
        },
        {
          "type": "frame",
          "id": "stage-2-cell-b",
          "layout": "vertical",
          "gap": 8,
          "padding": 0,
          "width": 200,
          "height": "fit-content",
          "fillColor": "transparent",
          "alignItems": "stretch",
          "justifyContent": "center",
          "children": [
                {
                  "type": "rect",
                  "id": "b-s2",
                  "width": "fill-container",
                  "height": "fit-content",
                  "fillColor": "#EAE6F3",
                  "borderColor": "#8569CB",
                  "borderWidth": 2,
                  "borderRadius": 8,
                  "text": "[阶段 2 节点]",
                  "fontSize": 14,
                  "textColor": "#1F2329",
                  "textAlign": "center",
                  "verticalAlign": "middle"
                }
              ]
            }
          ]
        }
      ]
    },
    {
      "type": "connector",
      "connector": {
        "from": "a-s1",
        "to": "b-s2",
        "lineShape": "polyline",
        "lineColor": "#BBBFC4",
        "lineWidth": 2,
        "endArrow": "arrow",
        "label": "[跨泳道交互]",
        "labelFillColor": "#FFFFFF"
      }
    }
  ]
}
```

- 垂直泳道示例：见上文“垂直泳道”

- 全泳道统一 `slotWidth/slotHeight/gap`，并为每个阶段生成占位 **stage cell**（空阶段 cell 透明但保留）
- Flex 容器内不写子节点 `x/y`；对齐通过 cell 索引与统一尺寸实现
- 只有真实阶段才在对应 cell 内生成卡片；空阶段不生成卡片但保留 cell 保证网格完整
- 连线必须放在 `nodes` 顶层，并连接具体步骤卡片 id，不要连接 `lane-*-body` 这类布局容器
- **水平泳道**：根容器用 `layout: "vertical"` 固定 `lanesGap`；lane body 用 `layout: "horizontal"`；cell 固定宽度 `slotWidth`；主轴 `gap` 统一
- **垂直泳道**：根容器用 `layout: "horizontal"` 固定 `lanesGap`；lane body 用 `layout: "vertical"`；cell 固定高度 `slotHeight`；主轴 `gap` 统一
- **泳道 title**：title 比步骤卡片更醒目，但仍只用字号、字重、文字色强调；不要给泳道 title 额外加背景条

## 陷阱

- **各泳道复用的 stage slots 不一致**：会导致同阶段错位；`slotWidth / slotHeight / gap` 必须全泳道统一
- **把 connector 放进 children**：会导致 schema 报错或无法连线（见 connectors.md）
- **把辅助容器画成可见元素**：lane body 或其他支撑 frame 必须保持 `fillColor: "transparent"`，除泳道分组容器外不要额外加边框
- **手写 waypoints 过早**：先让引擎自动绕线；只有在必要时才通过 waypoints 接管
- **连线过多**：按 connectors.md 的连线数量策略降采样，否则跨泳道线会互相遮挡导致不可读
