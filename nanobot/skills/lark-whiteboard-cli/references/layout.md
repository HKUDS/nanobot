# 布局系统

## 布局决策

> 不要靠关键词猜布局。先分析信息结构，再决定布局策略。
> 本文件负责说明通用布局原则与骨架模板；字段语义看 `references/schema.md`，完整场景范式看各 `scenes/*.md`。

总原则：**先定主布局，再定子布局。**

**快速判断**：
- **Flex**：按层分、按区排
- **Dagre**：关系网密、流程链主导
- **绝对定位**：空间位置承载信息（地理方位、拓扑坐标、物理面板等），用脚本计算坐标
- **默认选择**：拿不准时优先用 **Flex**


**Dagre 版式统一原则**：
1. Dagre 解决的是**拓扑关系**，不是自动把画布铺满。
2. Dagre 作为子容器嵌套时，默认是不透明节点（Opaque Node），先根据内部拓扑计算自身包围盒，再作为原子节点参与父层布局。若需连线穿透边界，须声明 `layout: "dagre"` + `layoutOptions: { isCluster: true }`。
3. 混合布局时，Flex 更适合负责分区与层次，Dagre 更适合负责局部复杂关系；但如果 Dagre 本身就是主布局，也完全可以直接承担整张图的主体拓扑。
4. 选用 Dagre 前先看三件事：**最长链路方向、分支是否对称、是否有长回边/重试回路**。哪一项失衡，哪一项就会把包围盒撑歪。
5. 长回边、失败重试、跨层返回等关系，优先收敛到局部；必要时拆成局部流程区或旁路说明，不要让一条边把整个 Dagre 宽度拉爆。
6. 若 Dagre 产物在父容器中出现明显单侧留白、宽高失衡或内容只占很小一部分，必须调整 `rankdir`、重构拓扑，或在父层补充对称信息区，不能原样交付。

**读代码画架构图**：扫目录结构（按层分 → Flex；按功能模块分 → 看依赖方向）→ grep import（单向→Flex；网状→ Dagre 或 Flex + Dagre）→ 拿不准 → 默认 Flex。

> **flex 容器内的 `x/y` 会被完全忽略！**

❌ 致命错误：
```json
{ "type": "frame", "layout": "vertical", "children": [
  { "type": "rect", "x": 100, "y": 0, "text": "成都" },
  { "type": "rect", "x": 540, "y": 0, "text": "康定" }
]}
```
✅ 正确：用 `layout: "none"` 或放在顶层 nodes 用 x/y。

> **`layout: "none"`（绝对定位）的容器必须有明确的固定宽高！**

❌ 致命错误：
```json
{ "type": "frame", "layout": "none", "width": "fit-content", "height": "fit-content", "children": [
  { "type": "rect", "x": 0, "y": 0, "text": "区域A" },
  { "type": "rect", "x": 500, "y": 0, "text": "区域B" }
]}
```
✅ 正确：必须给绝对定位容器明确的固定宽高：
```json
{ "type": "frame", "layout": "none", "width": 1064, "height": 680, "children": [
  { "type": "rect", "x": 0, "y": 0, "text": "区域A" },
  { "type": "rect", "x": 554, "y": 0, "text": "区域B" }
]}
```

**构建方式**：

| 布局类型               | 做法                                                                          |
| ---------------------- | ----------------------------------------------------------------------------- |
| 纯 Flex / Dagre        | 直接写 JSON                                                                   |
| 混合布局 (Flex包Dagre) | 直接写 JSON（外层先做分区，局部复杂关系交给 Dagre；若被嵌套，默认为不透明节点） |
| 极度依赖几何坐标的图   | 写脚本生成 JSON（node xxx.js）                                                |
| 需要精确避让的特殊线   | 脚本 + `--layout` 两阶段                                                      |

---

## 网格方法论

核心理念：**先画网格，再填内容**。

先回答三个问题：
1. **信息分几行几列？** 每组一行或一列
2. **每格多大？** 等宽还是有主次？
3. **行列间距多大？** 分区间 24-32px，同区内 12-16px

---

## 布局模式选择

| 模式 | 适用场景                     | DSL 映射                                                 |
| ---- | ---------------------------- | -------------------------------------------------------- |
| grid | 架构图、对比表、卡片墙、看板 | vertical frame 嵌套 horizontal frame                     |
| flow | 复杂流程图、微服务交互       | `layout: "dagre"`，由引擎自动计算网状连线排版            |
| tree | 组织架构、模块依赖           | `layout: "dagre"` 配 `rankdir: "TB"` 或根节点居中的 Flex |
| free | 地理位置布局、物理面板还原   | `layout: "none"` + x/y                                   |

大多数图表用 grid 或 flow 模式。只有节点坐标本身有强语义（如地图）时才用 free。

> 以上都是布局策略名称，DSL 的 `layout` 属性值只支持 `'horizontal'`、`'vertical'`、`'none'`、`'dagre'` 四种。

---

## DSL 与 CSS Flexbox 属性映射

| DSL 属性                         | 对应的 CSS 心智模型                                | 限制                                                                       |
| -------------------------------- | -------------------------------------------------- | -------------------------------------------------------------------------- |
| `layout: 'horizontal'`           | `flex-direction: row`                              | 不写 layout = 绝对定位                                                     |
| `layout: 'vertical'`             | `flex-direction: column`                           | 同上                                                                       |
| `layout: 'none'`                 | `position: absolute`（子节点用 x/y）               | 子节点不能用 `fill-container`；容器必须有固定宽高                          |
| `layout: 'dagre'`                | 类似 Mermaid / DOT 的有向图布局                    | 宽高只支持 `fit-content`；先按拓扑算包围盒再参与父层布局；嵌套时默认为不透明节点 |
| `width/height: 'fill-container'` | `flex: 1`（主轴）/ `align-self: stretch`（交叉轴） | 祖先必须有确定尺寸                                                         |
| `width/height: 'fit-content'`    | `width/height: auto`                               | —                                                                          |
| `alignItems`                     | 同 CSS `align-items`                               | 仅 `'start'`/`'center'`/`'end'`/`'stretch'`（无 flex- 前缀）               |
| `justifyContent`                 | 同 CSS `justify-content`                           | 仅 `'start'`/`'center'`/`'end'`/`'space-between'`/`'space-around'`         |
| `gap`                            | 同 CSS `gap`                                       | 必须显式写（不写节点会粘连）                                               |
| `padding`                        | 同 CSS `padding`                                   | 必须显式写。支持 `number` / `[v,h]` / `[t,r,b,l]`                          |

`alignItems` 默认值为 `'start'`（CSS Flexbox 默认 `stretch`）。需要等高卡片时必须显式写 `alignItems: 'stretch'`。
DSL 的语法是严格白名单，不能写原生 CSS 属性（不支持 `alignSelf`、`flexWrap`、`margin` 等）。

---

## DSL 注意事项

1. **frame 必须写 layout 属性**，不写时子节点全堆在左上角。

2. **fill-container 死锁陷阱**：使用 `fill-container` 时，祖先链中必须有固定宽度（或高度），否则和 `fit-content` 形成死锁，尺寸退化为 0。
   错误示例：
   ```json
   { "type": "frame", "layout": "horizontal", "width": "fit-content", "children": [
     { "type": "rect", "width": "fill-container" }
   ]}
   ```
   正确示例：
   ```json
   { "type": "frame", "layout": "horizontal", "width": 1200, "children": [
     { "type": "rect", "width": "fill-container" }
   ]}
   ```
3. **不要给 Dagre 套固定宽高的外框**：Dagre 产物尺寸由拓扑决定，无法提前预知。父容器应使用 `fit-content` 自适应，或直接让 Dagre 作为顶层容器，不要用固定像素框住它。
4. **`layout: 'none'` 的容器必须有固定宽高**，不要写成 `fit-content`，否则子节点绝对定位容易错乱。
5. **含文字节点高度用 fit-content**，引擎不支持 overflow，写死高度会截断文字。
6. **Shape 节点有内边距**：rect/ellipse/diamond/triangle 各边 12px；cylinder 垂直 +42px。
7. **不支持 flex-wrap**，需要换行时用嵌套 frame 模拟。
8. **图层顺序**：数组中越靠后的节点层级越高。需要叠加标注时放在数组最后。

---

## 布局选择指南

| 你要表达的关系             | 怎么排                   | DSL 写法                                                                     |
| -------------------------- | ------------------------ | ---------------------------------------------------------------------------- |
| 先后顺序、层级从上到下     | 纵向堆叠                 | `layout: 'vertical'`                                                         |
| 并列、同等重要、可对比     | 横向等分                 | `layout: 'horizontal'` + `alignItems: 'stretch'` + `width: 'fill-container'` |
| 区域有名称，名称在侧边     | 侧标签 + 内容并排        | 横向 frame: [text(标签), frame(内容)]                                        |
| 多个大分区，各自独立       | 分区纵向排列             | 纵向 frame 包多个彩色 frame                                                  |
| 一行放不下，需要换行       | 嵌套横向 frame 模拟换行  | 纵向 frame 包多个横向 frame                                                  |
| 复杂的网状关系、拓扑图     | **Dagre 有向图自动布局** | `layout: 'dagre'` + `layoutOptions.edges`                                    |
| 节点位置本身有含义（地图） | 绝对定位                 | `layout: 'none'` + x/y                                                       |

这些可以自由嵌套组合。比如：纵向堆叠(标题) + 分区纵向排列(多个层) + 每个层内横向等分(节点)。

---

## 布局示例

### 纵向堆叠（标题 + 内容）

```json
{
  "type": "frame", "layout": "vertical", "gap": 28, "padding": 32,
  "width": 1200, "height": "fit-content",
  "children": [
    { "type": "text", "width": "fill-container", "height": "fit-content",
      "text": "图表标题", "fontSize": 24, "textAlign": "center" },
    ...内容...
  ]
}
```

### 横向等分（并列元素）

```json
{
  "type": "frame", "layout": "horizontal", "gap": 16, "padding": 0,
  "width": "fill-container", "height": "fit-content",
  "alignItems": "stretch",
  "children": [
    { "type": "rect", "width": "fill-container", "height": "fit-content",
      "textAlign": "center", "verticalAlign": "middle", "text": "A" },
    { "type": "rect", "width": "fill-container", "height": "fit-content",
      "textAlign": "center", "verticalAlign": "middle", "text": "B" }
  ]
}
```

`alignItems: 'stretch'` + `width: 'fill-container'` = 等宽等高。

### 侧标签 + 内容

```json
{
  "type": "frame", "layout": "horizontal", "gap": 24, "padding": 0,
  "width": "fill-container", "height": "fit-content",
  "alignItems": "center",
  "children": [
    { "type": "text", "width": 160, "height": "fit-content",
      "text": "区域名称", "fontSize": 20, "textColor": "#1F2329", "textAlign": "right" },
    { "type": "frame", "width": "fill-container", "height": "fit-content",
      ...区域内容...
    }
  ]
}
```

不要用 frame 的 `title` 属性做标签——渲染为极小标题栏，不可读。

### 分区纵向排列

把内容划分为几个大区域，每个区域用不同颜色区分（颜色从 style 文件的色板选取）：

```json
{
  "type": "frame", "layout": "vertical", "gap": 28, "padding": 0,
  "width": "fill-container", "height": "fit-content",
  "children": [
    { "type": "frame", "borderRadius": 8,
      "layout": "horizontal", "gap": 16, "padding": 20, ...区域1... },
    { "type": "frame", "borderRadius": 8,
      "layout": "horizontal", "gap": 16, "padding": 20, ...区域2... }
  ]
}
```

### 模拟换行

一行放不下时，拆成多个横向 frame：

```json
{
  "type": "frame", "layout": "vertical", "gap": 8, "padding": 0,
  "children": [
    { "type": "frame", "layout": "horizontal", "gap": 8, "padding": 0,
      "children": [item1, item2, item3, item4] },
    { "type": "frame", "layout": "horizontal", "gap": 8, "padding": 0,
      "children": [item5, item6] }
  ]
}
```

## 复杂拓扑混合布局 (Dagre + Flex)

当你在处理**连线众多、关系杂乱的拓扑图 / 链路流程图 / 复杂架构图**时，不用手动去算每个节点坐标，优先考虑 **Flex + Dagre 的混合布局策略**。这主要包含两种维度的嵌套：

* **外层 Dagre + 内层 Flex（复杂节点）**：**这是最推荐的复杂架构画法**。整图拓扑交由 `layout: "dagre"` 自动计算并顺滑布线，而图中的节点不再只是单调的矩形，可以是一个用 Flex 自由拼装的复杂 `frame` 卡片（包含图标、主次标题、状态等），让节点承载更丰富的信息。
* **外层 Flex + 内层 Dagre（局部流程）**：外层用 Flex 或绝对定位划分大的业务区域，而某个特定区域内部放入 `layout: "dagre"` 容器负责处理局部的业务流。
  * **嵌套前先做宽度预判**：Dagre 会根据拓扑尽情往两侧撑出包围盒。如果可能横跨导致溢出，优先改 `rankdir` 为 `TB`、缩短文案、调小 `nodesep/ranksep`，必要时将超长的链路拆成分步区。

```json
{
  "type": "frame", "id": "arch_root",
  "layout": "dagre", "padding": 40,
  "width": "fit-content", "height": "fit-content",
  "layoutOptions": {
    "rankdir": "LR", "nodesep": 60, "ranksep": 100,
    "edges": [
      ["client", "auth_svc", "request"],
      ["auth_svc", "order_svc"],
      ["order_svc", "order_db"]
    ]
  },
  "children": [
    {
      "type": "frame", "id": "client",
      "layout": "vertical", "gap": 6, "padding": [12, 16],
      "alignItems": "center",
      "fillColor": "#F8FAFC", "borderColor": "#CBD5E1", "borderWidth": 2, "borderRadius": 10,
      "children": [
        { "type": "text", "text": "Client App", "fontSize": 14, "textColor": "#0F172A" },
        { "type": "text", "text": "React 18", "fontSize": 10, "textColor": "#64748B" }
      ]
    },
    {
      "type": "frame", "id": "cluster_gateway",
      "layout": "dagre", "layoutOptions": { "isCluster": true, "clusterTitle": "Gateway Tier", "clusterTitleColor": "#15803D" },
      "fillColor": "#F0FDF4", "borderColor": "#86EFAC",
      "borderWidth": 2, "borderDash": "dashed", "borderRadius": 16,
      "children": [
        { "type": "rect", "id": "auth_svc", "width": 120, "height": 40, "text": "Auth Service", "fillColor": "#DCFCE7", "borderColor": "#86EFAC", "borderWidth": 1, "borderRadius": 6, "fontSize": 12 },
        { "type": "rect", "id": "order_svc", "width": 120, "height": 40, "text": "Order Service", "fillColor": "#DCFCE7", "borderColor": "#86EFAC", "borderWidth": 1, "borderRadius": 6, "fontSize": 12 }
      ]
    },
    {
      "type": "frame", "id": "order_db",
      "layout": "vertical", "gap": 4, "padding": [10, 14],
      "alignItems": "center",
      "fillColor": "#FFFFFF", "borderColor": "#FECACA", "borderWidth": 2, "borderRadius": 10,
      "children": [
        { "type": "cylinder", "width": 50, "height": 36, "fillColor": "#FCA5A5", "borderColor": "#DC2626", "borderWidth": 1 },
        { "type": "text", "text": "Order DB", "fontSize": 12, "textColor": "#7F1D1D" }
      ]
    }
  ]
}
```

**示例要点**：
- `client` 和 `order_db` 是 **Flex 复合节点**（不透明节点），内部用 vertical 布局组合多行信息，对外层 Dagre 是固定宽高的原子。
- `cluster_gateway` 是 **透明子图**（`layout: "dagre"` + `isCluster: true`），外部连线可穿越边界直达 `auth_svc` 和 `order_svc`。
- 所有 `edges` 统一写在最外层根 Dagre 的 `layoutOptions` 中。

**Dagre 嵌套排版规则**：

1. **不透明节点（Opaque Node）**：Dagre 内的子容器，无论其内部 layout 是 flex、absolute 还是 dagre，只要未声明 isCluster: true，对外层 Dagre 就是具有确定宽高的不透明原子节点。外层连线无法寻址其内部子节点。
2. **连线兜底重定向（Edge Redirect Fallback）**：当 edges 引用了某不透明节点内部的子节点 ID 时，引擎自动将该连线端点重定向至其最近的不透明祖先节点。不报错，不产生悬空连线。
3. **透明子图（Compound Cluster）**：子容器同时声明 `layout: "dagre"` 与 `layoutOptions: { isCluster: true }` 时，成为外层 Dagre 的复合子图。其内部子节点直接参与外层拓扑运算，连线可穿越子图边界。子图自身不执行独立排版，尺寸由外层 Dagre 根据内部节点包围盒自动撑开。

---

## 绝对定位

当节点位置本身有含义（拓扑图、地图、时间线轴）时用绝对定位。大多数图表优先用 Flex。

### 混合布局

模块内部用 Flex 自动排版，模块之间用绝对定位自由摆放。注意：承载这些模块的 `layout: "none"` 父容器必须先给出**固定宽高**，再在里面摆放子模块。

```json
{
  "type": "frame", "layout": "none", "width": 1200, "height": 800,
  "children": [
    {
      "type": "frame", "id": "module-a", "x": 100, "y": 100,
      "width": 300, "height": "fit-content",
      "layout": "vertical", "gap": 8, "padding": 16,
      "children": [
        { "type": "rect", "width": "fill-container", "height": "fit-content", "text": "内容1" },
        { "type": "rect", "width": "fill-container", "height": "fit-content", "text": "内容2" }
      ]
    }
  ]
}
```

### 两阶段绘图

先出骨架图导出坐标，再基于坐标补充连线和注解：

```bash
npx -y @larksuite/whiteboard-cli@^0.2.0 -i skeleton.json -o step1.png -l coords.json
```

`coords.json` 包含每个带 id 节点的精确坐标（absX, absY, width, height）。

---

## 常用间距和尺寸

| 参数             | 常用范围    | 说明         |
| ---------------- | ----------- | ------------ |
| 整图宽度         | 1000-1400px | —            |
| 分区之间间距     | 24-32px     | —            |
| 同分区内节点间距 | 12-16px     | —            |
| 有连线的节点间距 | >= 40px     | 给箭头留空间 |
| 分区内边距       | 16-24px     | —            |
| 侧标签宽度       | 120-180px   | —            |

---

## 等大卡片

一排卡片需要等宽等高时，不要写固定像素：

```json
{
  "type": "frame", "layout": "horizontal", "gap": 16, "padding": 0,
  "alignItems": "stretch",
  "children": [
    { "type": "rect", "width": "fill-container", "height": "fit-content", "text": "A" },
    { "type": "rect", "width": "fill-container", "height": "fit-content", "text": "B" }
  ]
}
```

`alignItems: 'stretch'` + `width: 'fill-container'` = 等宽等高。
