# 漏斗图 (Funnel)

## Content 约束

- 阶段 3-6 个
- 每阶段一行标签 + 数值（如 "{{STAGE_NAME}} ({{PERCENTAGE}})"）
- 文案尽量简短；长文案外置到漏斗旁边，图形内仅保留核心短文案

## Layout 选型

绝对定位。用 `trapezoid` / `triangle` 节点从宽到窄排列，height 用 `fit-content`。

## Layout 规则

- 外层 frame 使用 `layout: "vertical"` + `alignItems: "center"` 居中对齐
- 所有层必须使用脚本计算宽度，以保证**绝对完美的等斜率（直线边缘）**。切勿手写拍脑袋的宽度！
- 每层间 gap 0-8px（紧密堆叠视觉效果好），从上到下宽度递减。注意 children 数组第一个元素是最顶层（最宽）
- 所有图形节点必须设置 `"vFlip": false`（引擎默认朝上翻转，漏斗需要朝下）
- 注意：因为 `vFlip: false` 且是倒金字塔结构，所以 `topWidth` 实际控制的是漏斗各层的**底部较窄边缘**。底层可用 `triangle`（`topWidth: 0`）收窄为尖角，或继续用 `trapezoid` 保持平底。

> **严格的斜率算法（必须在脚本中实现）**：
> 要让漏斗的侧边形成一条完美的直线，**宽度的递减必须与高度和 gap 严格挂钩**。
> 1. 设定整体宽度收缩系数 `angleK`（建议值 1.5 到 2.5，表示高度每增加1px，总宽度减少的像素数）。
> 2. 因为从上往下变窄，所以公式是减法：`bottomWidth(即 topWidth 属性) = currentWidth - (height * angleK)`
> 3. 下一层的顶宽公式（必须考虑 gap 带来的额外内收）：`nextLayerWidth = bottomWidth - (gap * angleK)`

## 脚本构建模板

必须使用 `node` 运行脚本生成 JSON。

```javascript
import fs from 'fs';

// 1. 配置基础参数
const GAP = 4;
const ANGLE_K = 2; // 斜率系数：高度每下降1px，宽度减少2px
const LAYER_HEIGHT = 80;

const data = [
  { text: "展现 (100%)", fillColor: "#F0F4FC", textColor: "#1F2329" },
  { text: "点击 (50%)", fillColor: "#EAE2FE", textColor: "#1F2329" },
  { text: "加购 (20%)", fillColor: "#DFF5E5", textColor: "#1F2329" },
  { text: "成交 (5%)", fillColor: "#1F2329", textColor: "#FFFFFF" }
];

// 计算第一层的初始宽度 (保证最底层缩到0或平底)
// 倒推公式：startWidth = 最后一层底宽 + 所有高度消耗 + 所有gap消耗
const totalHeightLoss = data.length * LAYER_HEIGHT * ANGLE_K;
const totalGapLoss = (data.length - 1) * GAP * ANGLE_K;
// 设定最底层为一个尖角 (底宽为0)
let currentWidth = 0 + totalHeightLoss + totalGapLoss;

const children = data.map((layer, index) => {
  // 2. 根据公式计算当前层的底宽 (对应节点的 topWidth 属性)
  const currentBottomWidth = currentWidth - (LAYER_HEIGHT * ANGLE_K);
  
  const node = {
    type: currentBottomWidth <= 0 ? "triangle" : "trapezoid",
    width: currentWidth,
    // 注意：漏斗中 topWidth 表示的是下方的窄边！如果 <=0 就用 triangle
    topWidth: Math.max(0, currentBottomWidth), 
    height: LAYER_HEIGHT,
    vFlip: false, // 必须为 false
    text: layer.text,
    textAlign: "center",
    fillColor: layer.fillColor,
    borderColor: layer.fillColor,
    borderWidth: 2,
    fontSize: 16,
    textColor: layer.textColor
  };

  // 3. 关键：计算下一层的顶宽。必须减去 gap 的向内收缩量！
  currentWidth = currentBottomWidth - (GAP * ANGLE_K);
  
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

- **不要手写随意递减的宽度**：这会导致漏斗侧边变成折线，不直。必须严格使用上述 `angleK` 公式计算。
- **忘记计算 gap 带来的收缩**：如果下一层的 `width` 只是简单等于上一层的 `topWidth`，在有 gap 的情况下，衔接处会产生锯齿折角。必须减去 `gap * angleK`。
- **vFlip 未设置**：忘记 `"vFlip": false` 会导致梯形朝上翻转，漏斗形状错误
- **文字溢出底层**：底层越窄空间越小，短文案用 `\n` 换行，长文案外置到漏斗旁边（外层套 `layout: "horizontal"` 的 frame，漏斗一侧，说明文字另一侧）
