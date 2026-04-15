# 连线系统

## 连线策略

| 连线数 | 策略 |
|--------|------|
| ≤8 | 逐条画 |
| 9-15 | 代表性连线（每层选 1-2 个节点连到下一层）|
| >15 | 层到层连线，或回退精简分组 |

一个节点有 3+ 条连线时：入线从 top，出线从 bottom，同侧多条线用不同方向分散。

---

## connector 必须放根 nodes 数组

```typescript
// 错误：connector 放在 frame children 里
{ type: 'frame', children: [
  { type: 'connector', ... }  // 会导致 Schema 报错或无法连线！
]}

// 正确：connector 放在根 nodes 数组
const doc: WBDocument = {
  version: 2,
  nodes: [
    { type: 'frame', id: 'box', ... },
    { type: 'connector', ... },  // 必须和顶层 frame 平级
  ],
};
```

---

## 箭头默认值

- `endArrow` 省略时默认为 `'arrow'`（即连线末端默认带箭头）。
- `startArrow` 省略时默认为 `'none'`（即连线起始端默认无箭头）。

---

## 连线技巧

```typescript
// 自动绕线（推荐）：仅需指定节点 id（引擎可自动推断最优出线方向），并使用 polyline 或 rightAngle 形状
// 只要不传 waypoints，引擎会尝试自动避开障碍物并生成折线。
{ type: 'connector', connector: {
  from: 'a', to: 'b', // fromAnchor 和 toAnchor 也可以省略，让引擎自己找最短路径
  lineShape: 'polyline', lineColor: '#000000', lineWidth: 2, endArrow: 'arrow' }}

// 精确坐标（做注解箭头）
{ type: 'connector', connector: {
  from: { x: 150, y: 200 }, to: 'b', toAnchor: 'left',
  lineShape: 'curve', lineColor: '#BBBFC4', lineWidth: 2,
  lineStyle: 'dashed', endArrow: 'triangle' }}

// 手动控制路径点 waypoints（仅在需要强制固定路线、或者自动路由不符合预期时使用）
// 注意：一旦提供了 waypoints，引擎将严格尊重这些点，不再进行自动避障。
{ type: 'connector', connector: {
  from: { x: 300, y: 140 }, to: { x: 300, y: 340 },
  waypoints: [{ x: 350, y: 140 }, { x: 350, y: 340 }],
  lineShape: 'polyline', lineColor: '#000000', lineWidth: 2, endArrow: 'arrow' }}

// 绘制坐标轴/数轴（必须使用 straight，防止刻度文字触发自动避障导致线条弯曲）
{ type: 'connector', connector: {
  from: { x: 100, y: 400 }, to: { x: 600, y: 400 },
  lineShape: 'straight', lineColor: '#000000', lineWidth: 2, endArrow: 'arrow' }}
```

> [!IMPORTANT]
> **1. 形状选用要求（核心）**，需明确 `lineShape` 类型：
> - **`'polyline'`（圆角折线）**：**默认首选**。适用于流程图、架构图等绝大多数场景。支持引擎的**自动绕线与避障**功能（只需指定 `from` 和 `to`）。
> - **`'rightAngle'`（直角折线）**：适用于明确要求“总线/直角规约”、树状层级严格对齐的场景，同样支持**自动绕线与避障**。
> - **`'straight'`（直线）**：不受自动避障机制的影响，适用于**坐标轴、数轴、几何图形边框、直接指向关系**等要求线条绝对笔直、不允许出现任何绕行或弯曲的场景。
> - **`'curve'`（曲线）**：适用于优雅的跨层连线（S型弯）、自由发散的脑图分支、或做注解箭头时。
> - **注意**：你需要根据当前绘制的图表类型和上下文语境，选择最合适的 `lineShape`。不要盲目全部使用 `polyline`，例如在绘制坐标系时必须主动切换为 `straight`。
> **2. 间距要求**：有 connector 连线的卡片间 gap 需 ≥ 40，否则箭头挤在缝里看不清。
> **3. 顶层约束**：`connector` 必须直接放在 `WBDocument.nodes`，**严禁**嵌套在 `children` 内。建议在数据末尾统一声明连线。
>
> [!TIP]
> **自动绕线 vs 手动控制**
> - **优先依赖自动绕线**：对于 `'polyline'` 和 `'rightAngle'`，引擎会自动规划路径并尝试避开障碍物（`fromAnchor` 和 `toAnchor` 也可省略，引擎会自动推断最优出线方向），这是最推荐的方式。
> - **何时手动算 waypoints**：**仅在必要时**（例如自动路由不符合预期，或者必须强制走特定形状绕开特定元素时），才需要通过 `waypoints` 手动接管坐标序列。
>
> **连线标签**
> - **连线文字说明**：需要文字说明时，可用 `label` 标注。

---

## 锚点方向规则

锚点（top/right/bottom/left）表示连线从节点的哪个边出发，方向含义与 CSS border 四边相同。

**注意：由于目前自动绕线功能支持省略锚点让引擎自动推断，以下规则主要适用于你想强制控制出线方向，或者使用直线/曲线时的场景。**

选择锚点时根据两个节点的相对位置：目标在下方用 `fromAnchor: 'bottom'` + `toAnchor: 'top'`，目标在右侧用 `fromAnchor: 'right'` + `toAnchor: 'left'`。如果手动指定了锚点，必须与节点的实际相对位置匹配，否则可能导致连线反向绕行。

**锚点绑定的常见范式**：
- **同层横向推进**（目标在正右）：`fromAnchor: "right"` -> `toAnchor: "left"`
- **垂直下沉推进**（目标在正下）：`fromAnchor: "bottom"` -> `toAnchor: "top"`
- **跨层斜切推进**（目标在左下或右下）：首选 **`fromAnchor: "bottom"` -> `toAnchor: "top"`**。由于线段自身带有重力倾向，从底部出线再弯曲进入下一层顶部，完美契合流水线的 S 型大弯，能画出最优雅顺滑的跨层曲线。**避免**使用左右锚点互相跨接。
- **逆流回捞**（底部发散回指顶部原点）：首选 **`fromAnchor: "top"` -> `toAnchor: "bottom"`** 配合 `lineStyle: "dashed"`。
