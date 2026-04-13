# 金字塔图 (Pyramid)

## Content 约束

- 层级 3-6 个，从底到顶宽度递减
- 每层一个短标签（如关键词或短语）
- 长文案外置到金字塔旁边，图形内仅保留核心短文案

## Layout 选型

vertical frame + 每层宽度递减。gap 4px 保持紧密。

## Layout 规则

- 外层 frame 使用 `layout: "vertical"` + `alignItems: "center"`
- 所有层必须使用脚本计算宽度，以保证**绝对完美的等斜率（直线边缘）**。切勿手写拍脑袋的宽度！
- children 数组中第一个元素是顶层（最窄），最后一个是底层（最宽）。
- 顶层通常用 `triangle`（`topWidth: 0`），中间和底层用 `trapezoid`。
- gap 通常设为 4px 保持紧密的金字塔感。

> **严格的斜率算法（必须在脚本中实现）**：
> 要让金字塔的侧边形成一条完美的直线，**宽度的增量必须与高度和 gap 严格挂钩**。
> 1. 设定整体宽度扩张系数 `angleK`（建议值 1.5 到 2.5，表示高度每增加1px，总宽度增加的像素数）。
> 2. 当前层的底宽公式：`width = topWidth + (height * angleK)`
> 3. 下一层的顶宽公式（必须考虑 gap 带来的额外外扩）：`nextTopWidth = width + (gap * angleK)`

## 脚本构建模板

必须使用 `node` 运行脚本生成 JSON。

```javascript
import fs from 'fs';

// 1. 配置基础参数
const GAP = 4;
const ANGLE_K = 2; // 斜率系数：高度每增加1px，宽度增加2px
const LAYER_HEIGHT = 80;

const data = [
  { text: "顶层核心", fillColor: "#1F2329", textColor: "#FFFFFF" },
  { text: "中间层 B", fillColor: "#DFF5E5", textColor: "#1F2329" },
  { text: "中间层 A", fillColor: "#EAE2FE", textColor: "#1F2329" },
  { text: "最底层基础", fillColor: "#F0F4FC", textColor: "#1F2329" }
];

let currentTopWidth = 0; // 顶层如果是尖角，初始为 0
const children = data.map((layer, index) => {
  // 2. 根据公式计算当前层的底宽
  const currentBottomWidth = currentTopWidth + (LAYER_HEIGHT * ANGLE_K);
  
  const node = {
    type: currentTopWidth === 0 ? "triangle" : "trapezoid",
    width: currentBottomWidth,
    topWidth: currentTopWidth,
    height: LAYER_HEIGHT,
    text: layer.text,
    textAlign: "center",
    fillColor: layer.fillColor,
    borderColor: layer.fillColor,
    borderWidth: 2,
    fontSize: 16,
    textColor: layer.textColor
  };

  // 3. 关键：计算下一层的顶宽。必须把 gap 的延伸也算进去！
  currentTopWidth = currentBottomWidth + (GAP * ANGLE_K);
  
  return node;
});

const output = {
  version: 2,
  nodes: [
    {
      type: "frame",
      layout: "vertical",
      alignItems: "center",
      gap: GAP,
      padding: 40,
      children: children
    }
  ]
};

fs.writeFileSync('diagram.json', JSON.stringify(output, null, 2));
```

## 陷阱

- **不要手写随意递增的宽度**：这会导致金字塔侧边变成折线，不直。必须严格使用上述 `angleK` 公式计算。
- **忘记计算 gap 带来的扩展**：如果下一层的 `topWidth` 只是简单等于上一层的 `width`，在有 gap 的情况下，衔接处会产生锯齿折角。必须加上 `gap * angleK`。
- **从上到下排列错误**：children 数组第一个是顶层（最窄），最后一个是底层（最宽），宽度依次递增。
- **文字溢出顶层三角形**：顶层三角形内部可用空间极小。短文案用 `\n` 手动换行；长文案外置到金字塔旁边（外层套 horizontal frame，金字塔左侧，说明文字右侧）
- **倒金字塔误用**：如果用户要求"倒金字塔"、"漏斗图"或"自上而下递减的结构"，**不要**使用本文件，切换到 `scenes/funnel.md`

## 扩展

- **辅助说明**：需要在旁边添加文字说明时，在最外层套一个 `layout: "horizontal"` 的 frame，金字塔放左侧，说明文字（vertical 排列的 text 节点）放右侧
- **配色**：各层颜色应从色板中选取不同颜色以示区分（如蓝→紫→绿→黄递进）
