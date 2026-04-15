# DSL Schema

> 本文件只说明 **DSL 里能写什么**：节点类型、字段、枚举值、硬约束。布局策略、组合方法、Dagre/Flex 心智模型统一放在 `references/layout.md`。  
> `?` 表示该字段在 schema 层是 optional；若需要稳定产出，再参考对应 scene 或 layout 文件中的最佳实践。

**📝 布局引擎核心法则**：
- **基本行为与 Flexbox 等同**：Frame 布局基于 Yoga 引擎。`layout: 'horizontal'` = `flex-direction: row`，`fill-container` = `flex: 1`，`fit-content` = `width: auto`，`gap` / `padding` / `alignItems` / `justifyContent` 语义相同。
- **枚举值无 flex- 前缀**：一律使用 `'start'` / `'end'` 而非原生 CSS 的 `'flex-start'` / `'flex-end'`。
- **默认对齐的差异**：`alignItems` 的默认值是 `'start'`（原生 CSS 默认是 `stretch`）。所以同排卡片需要等高时，**必须显式声名** `alignItems: 'stretch'`。
- **Dagre 引擎的特殊性**：`layout: 'dagre'` 作为专属拓扑连线引擎，自身不支持 `fill-container` 宽高，对其父容器而言，它是一个自适应（打包裹）的黑盒。

## WBDocument

```typescript
interface WBDocument {
  version: 2;
  nodes: WBNode[];   // 顶层节点。connector 必须放在这里，不能嵌套在 children 中
}
```

## 节点类型

### Frame（容器）

唯一可以包含子节点的类型。用于分组、布局、背景。

```typescript
{
  type: 'frame';
  id?: string;
  x?: number; y?: number;       // Flex 子节点不需要 x/y
  width: WBSizeValue;
  height: WBSizeValue;
  layout: 'horizontal' | 'vertical' | 'none' | 'dagre';  // 布局模式
  gap: number;                    // 必须显式写（不写节点会粘连，容易出 bug）
  padding: number | [number, number] | [number, number, number, number]; // 必须显式写（不写内容贴边）
  justifyContent?: 'start' | 'center' | 'end' | 'space-between' | 'space-around';
  alignItems?: 'start' | 'center' | 'end' | 'stretch';
  layoutOptions?: {                 // 仅当 layout 为 'dagre' 时生效
    rankdir?: 'TB' | 'BT' | 'LR' | 'RL';
    nodesep?: number;
    edgesep?: number;
    ranksep?: number;
    edges?: Array<[string, string] | [string, string, string]>; // [fromId, toId, label?] 引擎自动排版子节点并生成贝塞尔曲线连线
    isCluster?: boolean;            // 透明子图。为 true 时子节点参与父级 Dagre 拓扑运算，连线可穿越边界
    clusterTitle?: string;          // 子图悬浮标题（自动吸附左上角）
    clusterTitleColor?: string;     // 标题颜色 (HEX格式，如 "#8B5CF6")
  };
  fillColor?: string;
  borderColor?: string;
  borderWidth?: number;
  borderDash?: 'solid' | 'dashed' | 'dotted';
  borderRadius?: number;
  children?: WBNode[];           // 不能包含 connector
}
```

**Dagre 嵌套排版规则**：

1. **不透明节点（Opaque Node）**：Dagre 内的子容器，无论 `layout` 是 `flex`、`absolute` 还是 `dagre`，只要未声明 `isCluster: true`，对外层 Dagre 就是具有确定宽高的不透明原子节点。外层连线无法寻址其内部子节点。
2. **连线兜底重定向（Edge Redirect Fallback）**：当 `edges` 引用了某不透明节点内部的子节点 ID 时，引擎自动将该连线端点重定向至其最近的不透明祖先节点。不报错，不产生悬空连线。
3. **透明子图（Compound Cluster）**：子容器同时声明 `layout: "dagre"` 与 `layoutOptions: { isCluster: true }` 时，成为外层 Dagre 的复合子图。其内部子节点直接参与外层拓扑运算，连线可穿越子图边界。子图自身不执行独立排版，尺寸由外层 Dagre 根据内部节点包围盒自动撑开。

**isCluster 最小用法**：
```json
{
  "type": "frame", "id": "cluster_a",
  "layout": "dagre", "layoutOptions": { "isCluster": true },
  "fillColor": "#F0FDF4", "borderColor": "#86EFAC", "borderWidth": 2, "borderDash": "dashed", "borderRadius": 16,
  "children": [
    { "type": "text", "text": "区域标题", "fontSize": 11, "textColor": "#15803D" },
    { "type": "rect", "id": "node_inside", "width": 120, "height": 40, "text": "内部节点" }
  ]
}
```
> 注意：`edges` 必须写在**最外层的根 Dagre** 的 `layoutOptions` 中，不要写在 cluster 内部。
**其他约束**：
- `layout / gap / padding` 在 schema 层是 optional，但实际生成时推荐显式写出，避免依赖默认行为。
- `layoutOptions` 仅在 `layout: 'dagre'` 时生效。
- `children` 里不能出现 `connector`。

> **虚拟 frame 陷阱**：没有 `fillColor`、`borderColor`、`borderWidth` 的 frame 在编译时可能被当作纯布局容器跳过（子节点直接提升到父级）。如果给这种 frame 设了 `id` 并让外部 connector 连接它，编译后 frame 消失，connector 引用会失效。需要保留这个 frame 时，请给它加上不会被优化掉的外观属性。

### 基础图形

```typescript
{
  type: 'rect' | 'ellipse' | 'cylinder' | 'diamond' | 'triangle' | 'trapezoid';
  id?: string;
  x?: number; y?: number;
  opacity?: number;              // 0-1，仅影响 fillColor 的透明度（对 frame/text/stickyNote 无效）
  vFlip?: boolean;
  hFlip?: boolean;
  width: WBSizeValue;
  height: WBSizeValue;
  fillColor?: string;
  borderColor?: string;
  borderWidth?: number;
  borderDash?: 'solid' | 'dashed' | 'dotted';
  borderRadius?: number;
  topWidth?: number;             // 仅对 triangle / trapezoid 有效，梯形顶边宽度或三角形顶角截断宽度
  text?: string | WBTextRun[];   // 纯文本或富文本
  fontSize?: number;
  textColor?: string;
  textAlign?: 'left' | 'center' | 'right';     // Shape 默认 'center'（与 CSS 不同）
  verticalAlign?: 'top' | 'middle' | 'bottom';  // Shape 默认 'middle'（与 CSS 不同）
}
```

> **cylinder 约束**：cylinder 的弧度固定 16px，不随宽度缩放。宽度过大会变成扁椭圆。禁止 `width: "fill-container"`，必须用固定宽度 + `height: "fit-content"`。宽度根据文字长度选择，通常 120-200px。

> **Shape 内边距（TEXT_INSET）**：Shape 节点有强制内边距，fit-content 会自动补偿。
> - rect / ellipse / diamond / triangle：上下左右各 12px
> - cylinder：顶部弧形 32px + 底部弧形 10px（垂直 +42px），水平各 7px
>
> 需要手算固定尺寸时：`实际文字宽/高 + 对应 inset`。
> 例：rect 内 14px 字号两行文字高 ~32px → `height >= 32 + 24 = 56px`

### Text（纯文本节点）

```typescript
{
  type: 'text';
  id?: string;
  x?: number; y?: number;
  width: WBSizeValue;
  height: WBSizeValue;
  text?: string | WBTextRun[];
  fontSize?: number;
  textColor?: string;
  textAlign?: 'left' | 'center' | 'right';
  verticalAlign?: 'top' | 'middle' | 'bottom';
}
```

### StickyNote（便签）

```typescript
{
  type: 'stickyNote';
  id?: string;
  x?: number; y?: number;
  width: WBSizeValue;
  height: WBSizeValue;
  fillColor?: '#FEF1CE' | '#F5D1A7' | '#DFF5E5' | '#CDF7CC' | '#C9E8EF' | '#D6DCF3' | '#D3CCEE' | '#F1C5E7' | '#F6C8C8'; // 便签底色（仅支持这 9 种）
  text?: string | WBTextRun[];
  fontSize?: number;
  textColor?: string;
  textAlign?: 'left' | 'center' | 'right';
  verticalAlign?: 'top' | 'middle' | 'bottom';
}
```

### Connector（连线）

必须放在顶层 `nodes` 数组中，不能嵌套在 frame 的 `children` 里。

```typescript
{
  type: 'connector';
  id?: string;
  connector: {
    from: string | { x: number; y: number };   // 节点 id 或坐标
    to:   string | { x: number; y: number };
    fromAnchor?: 'top' | 'right' | 'bottom' | 'left';
    toAnchor?:   'top' | 'right' | 'bottom' | 'left';
    lineShape?:  'straight' | 'polyline' | 'curve' | 'rightAngle'; // 直线、圆角折线、曲线、直角折线
    lineColor?: string;
    lineWidth?: number;
    lineStyle?: 'solid' | 'dashed' | 'dotted';
    startArrow?: 'none' | 'arrow' | 'triangle' | 'circle' | 'diamond';
    endArrow?:   'none' | 'arrow' | 'triangle' | 'circle' | 'diamond';
    waypoints?: { x: number; y: number }[];  // polyline 途经点
    label?: string;                          // 连线中间的标签文字
    labelPosition?: number;                  // 标签位置，0-1，默认 0.5（中点）
  };
}
```

### SVG

```typescript
{
  type: 'svg';
  id?: string;
  x?: number; y?: number;
  opacity?: number;
  width: WBSizeValue;
  height: WBSizeValue;
  svg: { code: string };         // SVG 代码字符串
}
```

#### 渲染规范

SVG 通过 `image/svg+xml` Blob 加载到画布，**不在 HTML DOM 中**，因此存在严格限制：

**必须**：
- 包含 `viewBox` 属性（如 `viewBox="0 0 24 24"`），引擎依赖它确定坐标系
- 包含 `xmlns="http://www.w3.org/2000/svg"`（SVG 作为独立 `image/svg+xml` 解析时，XML 规范要求声明命名空间）

**允许的元素**（纯几何绘制）：
- 基本图形：`<rect>` `<circle>` `<ellipse>` `<line>` `<polyline>` `<polygon>` `<path>`
- 渐变/滤镜：`<defs>` `<linearGradient>` `<radialGradient>` `<filter>` `<feGaussianBlur>` `<feMerge>`
- 结构：`<g>` `<clipPath>` `<mask>` `<use>`

**禁止的元素**（字体和外部资源在 Blob 沙箱中无法加载）：
- `<text>` `<tspan>`（用同层 DSL rect 节点 + text 属性替代）
- `<image>`（用同层 DSL image 节点替代）
- `<foreignObject>`
- 任何引用外部 URL 的属性（`xlink:href` 指向远程资源等）

#### 两种典型用法

**1. 背景装饰 SVG**（大尺寸，与 frame 同大小）

用于绘制连线、曲线、发光效果等几何背景。文字信息通过同一 frame 内的 rect 节点叠加：

```json
{
  "type": "frame", "width": 1400, "height": 680, "layout": "none",
  "children": [
    { "type": "svg", "x": 0, "y": 0, "width": 1400, "height": 680,
      "svg": { "code": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 1400 680\" ...>...</svg>" } },
    { "type": "rect", "x": 100, "y": 50, "width": 200, "height": 40,
      "text": "Label", "fillColor": "transparent" }
  ]
}
```

**2. 内联图标 SVG**（24-48px，Feather/Lucide 风格）

用于卡片/按钮中的小图标，纯 stroke 线条：

```json
{ "type": "svg", "width": 32, "height": 32,
  "svg": { "code": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#3B82F6\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"12\" cy=\"12\" r=\"10\"/><polyline points=\"12 6 12 12 16 14\"/></svg>" } }
```

### Icon（内置图标）

引用画板内置图标库的图标。比手写 SVG 更简单——只需指定 `name`。

```typescript
{
  type: 'icon';
  id?: string;
  x?: number; y?: number;
  width?: WBSizeValue;          // 默认 48
  height?: WBSizeValue;         // 默认 48，保持正方形
  name: string;                 // 图标名称，从 npx -y @larksuite/whiteboard-cli@^0.2.0 --icons 输出中选取
  color?: string;               // 可选颜色覆盖，hex 格式如 '#FF6600'
}
```

**获取可用图标**：规划好内容和布局后，运行以下命令查看所有可用图标名，从中选取：
```bash
npx -y @larksuite/whiteboard-cli@^0.2.0 --icons
```

用法：
```json
{ "type": "icon", "id": "db", "name": "database", "width": 48, "height": 48 }
```

**使用建议**：
- 当图表中的节点代表具体事物（服务器、用户、数据库等）时，用图标比纯文字方块更直观
- 一张图 3-8 个图标为宜，为关键组件配图标，次要节点用普通形状
- 用 `color` 为图标指定合适的颜色, 比如与所在容器的配色一致
- 图标可放在 frame 子元素中参与 flex 布局，连线可通过 id 连接到图标
- 图标+文字组合：frame(vertical) 中放 icon + text，形成富组件

```json
{
  "type": "frame", "layout": "vertical", "gap": 8, "padding": 12,
  "alignItems": "center", "fillColor": "#F0F5FF", "borderColor": "#ADC6FF",
  "children": [
    { "type": "icon", "id": "db-icon", "name": "database", "width": 36, "height": 36 },
    { "type": "text", "text": "PostgreSQL", "fontSize": 12, "width": "fit-content", "height": "fit-content" }
  ]
}
```

---

## 富文本 WBTextRun

`text` 字段可以是纯字符串或 `WBTextRun[]` 数组。类似 HTML 内联样式：bold 对应 `<b>`，italic 对应 `<i>`，listType 对应 `<ol>/<ul>`。每个 run 是一段带样式的文字：

```typescript
interface WBTextRun {
  content: string;               // 文字内容，可含 \n 换行
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strikeThrough?: boolean;
  fontSize?: number;
  color?: string;                // 文字颜色
  backgroundColor?: string;     // 文字高亮背景
  hyperlink?: string;
  listType?: 'none' | 'ordered' | 'unordered';
  indent?: number;               // 缩进级数
  quote?: boolean;               // 引用块
}
```

示例：

```json
{
  "text": [
    { "content": "标题文字\n", "bold": true, "fontSize": 16 },
    { "content": "正文内容，", "fontSize": 14 },
    { "content": "高亮部分", "backgroundColor": "#FEF1CE", "fontSize": 14 }
  ]
}
```

`text` 和 `content` 中出现的双引号必须写成 `\"`，这是 JSON 规范要求。换行用 `\n`（JSON 中写为 `"第一行\n第二行"`，不要双重转义为 `\\n`）。

---

## 尺寸值 WBSizeValue

| 值                    | 含义                        | 注意                                   |
| --------------------- | --------------------------- | -------------------------------------- |
| `number`              | 固定像素                    | 任何场景                               |
| `'fit-content'`       | 由内容决定大小              | 父级需要 Flex 布局                     |
| `'fit-content(N)'`    | 同上，无内容时 fallback N   | 同上                                   |
| `'fill-container'`    | 填满父级剩余空间            | 父级需要 Flex 布局，且祖先链有固定宽度 |
| `'fill-container(N)'` | 同上，无 Flex 时 fallback N | —                                      |

`fill-container` 在 `layout: 'none'`（绝对定位）下无效。`fit-content` 仍可用于含文字节点（引擎通过 Yoga measureFunc 测量文字尺寸）。
