# 柱状图

## Content 约束

- 数据点 ≤ 12
- 同一数据系列用同一颜色（不要每个柱不同色）
- Y 轴必须有单位标注（如 "万元"、"人次"）

## Layout 选型

- **脚本生成坐标**（推荐）：用 .js 脚本计算柱体位置和高度，脚本输出 JSON 文件后调用 `npx -y @larksuite/whiteboard-cli@^0.2.0` 渲染
- **绝对定位手写**：简单柱状图（≤ 5 个柱）可手写坐标

## Layout 规则

- 白板坐标系 Y 轴向下为正，图表"底部原点"拥有最大 Y 值，柱体向上生长时 Y 减小
- 柱体等宽等间距，底部对齐 X 轴
- 柱体高度：`height = (value / maxValue) * chartHeight`
- 柱体 Y 坐标：`y = originY - height`
- 坐标轴用 connector 直线，末端带箭头（endArrow: "arrow"）
- 格线用虚线 connector（lineStyle: "dashed"，endArrow: "none"）
- 刻度线短横线 connector（endArrow: "none"）
- 数值标注放在柱体顶部上方
- 类别标签放在 X 轴下方，居中对齐柱体

## 坐标与尺寸计算指南

白板坐标系中，**X 轴向右为正，Y 轴向下为正**。因此图表的"底部原点"实际上拥有最大的 Y 坐标，图形向上生长时 Y 坐标在不断减小。

1. **确定图表区域**：
   - 设定图表区高度 `chartHeight` 和宽度 `chartWidth`
   - 设定左下角坐标原点 `(originX, originY)`
   - 示例：originX=80, originY=480, chartWidth=1000, chartHeight=400
2. **Y 轴映射（计算高度）**：
   - 找出数据的最大值 `maxValue`
   - 将 maxValue 向上取整到"整数刻度"（如数据最大 190 → maxValue 取 200）
   - 柱子高度：`height = (value / maxValue) * chartHeight`
   - 柱子 Y 坐标：`y = originY - height`
3. **X 轴映射（计算宽度与 X 坐标）**：
   - 将 chartWidth 按数据个数均分：`slotWidth = chartWidth / barCount`
   - 设定柱子间距 `barGap`（推荐 slotWidth 的 25%-30%）
   - 柱子宽度：`barWidth = slotWidth - barGap`
   - 第 i 根柱子 X 坐标：`x = originX + i * slotWidth + barGap / 2`
4. **Y 轴刻度计算**：
   - 将 0 到 maxValue 等分为 4-6 个刻度
   - 每个刻度的 Y 坐标：`gridY = originY - (tickValue / maxValue) * chartHeight`
   - 刻度线：从 (originX-10, gridY) 到 (originX, gridY) 的短横线
   - 网格线：从 (originX, gridY) 到 (originX+chartWidth, gridY) 的虚线

## 完整 JSON 示例

以下示例：3 根柱子，数据 [120, 200, 150]，maxValue=200，originX=80, originY=480, chartWidth=900, chartHeight=400。

- slotWidth = 900 / 3 = 300
- barGap = 80, barWidth = 220
- 刻度：0, 50, 100, 150, 200（每 50 一格，gridInterval = 80px）

```json
{
  "version": 2,
  "nodes": [
    { "type": "rect", "x": 0, "y": 0, "width": 1100, "height": 580 },

    { "type": "text", "x": 80, "y": 10, "width": 900, "height": "fit-content",
      "text": "季度销售额对比", "fontSize": 24, "textAlign": "center" },

    { "type": "text", "x": 10, "y": 40, "width": 60, "height": "fit-content",
      "text": "万元", "fontSize": 12, "textAlign": "center" },

    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 480 }, "to": { "x": 80, "y": 55 },
      "lineShape": "straight", "lineWidth": 2, "endArrow": "arrow"
    }},
    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 480 }, "to": { "x": 1000, "y": 480 },
      "lineShape": "straight", "lineWidth": 2, "endArrow": "arrow"
    }},

    { "type": "connector", "connector": {
      "from": { "x": 70, "y": 480 }, "to": { "x": 80, "y": 480 },
      "lineShape": "straight", "lineWidth": 1,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "text", "x": 20, "y": 470, "width": 50, "height": 20,
      "text": "0", "fontSize": 12, "textAlign": "right" },

    { "type": "connector", "connector": {
      "from": { "x": 70, "y": 400 }, "to": { "x": 80, "y": 400 },
      "lineShape": "straight", "lineWidth": 1,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "text", "x": 20, "y": 390, "width": 50, "height": 20,
      "text": "50", "fontSize": 12, "textAlign": "right" },
    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 400 }, "to": { "x": 980, "y": 400 },
      "lineShape": "straight", "lineWidth": 1, "lineStyle": "dashed",
      "startArrow": "none", "endArrow": "none"
    }},

    { "type": "connector", "connector": {
      "from": { "x": 70, "y": 320 }, "to": { "x": 80, "y": 320 },
      "lineShape": "straight", "lineWidth": 1,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "text", "x": 20, "y": 310, "width": 50, "height": 20,
      "text": "100", "fontSize": 12, "textAlign": "right" },
    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 320 }, "to": { "x": 980, "y": 320 },
      "lineShape": "straight", "lineWidth": 1, "lineStyle": "dashed",
      "startArrow": "none", "endArrow": "none"
    }},

    { "type": "connector", "connector": {
      "from": { "x": 70, "y": 240 }, "to": { "x": 80, "y": 240 },
      "lineShape": "straight", "lineWidth": 1,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "text", "x": 20, "y": 230, "width": 50, "height": 20,
      "text": "150", "fontSize": 12, "textAlign": "right" },
    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 240 }, "to": { "x": 980, "y": 240 },
      "lineShape": "straight", "lineWidth": 1, "lineStyle": "dashed",
      "startArrow": "none", "endArrow": "none"
    }},

    { "type": "connector", "connector": {
      "from": { "x": 70, "y": 160 }, "to": { "x": 80, "y": 160 },
      "lineShape": "straight", "lineWidth": 1,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "text", "x": 20, "y": 150, "width": 50, "height": 20,
      "text": "200", "fontSize": 12, "textAlign": "right" },
    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 160 }, "to": { "x": 980, "y": 160 },
      "lineShape": "straight", "lineWidth": 1, "lineStyle": "dashed",
      "startArrow": "none", "endArrow": "none"
    }},

    { "type": "rect", "id": "bar-0", "x": 120, "y": 240,
      "width": 220, "height": 240, "borderRadius": 4 },
    { "type": "text", "x": 120, "y": 215,
      "width": 220, "height": 20,
      "text": "120", "fontSize": 14, "textAlign": "center" },
    { "type": "text", "x": 120, "y": 490,
      "width": 220, "height": 30,
      "text": "Q1", "fontSize": 14, "textAlign": "center" },

    { "type": "rect", "id": "bar-1", "x": 420, "y": 80,
      "width": 220, "height": 400, "borderRadius": 4 },
    { "type": "text", "x": 420, "y": 55,
      "width": 220, "height": 20,
      "text": "200", "fontSize": 14, "textAlign": "center" },
    { "type": "text", "x": 420, "y": 490,
      "width": 220, "height": 30,
      "text": "Q2", "fontSize": 14, "textAlign": "center" },

    { "type": "rect", "id": "bar-2", "x": 720, "y": 180,
      "width": 220, "height": 300, "borderRadius": 4 },
    { "type": "text", "x": 720, "y": 155,
      "width": 220, "height": 20,
      "text": "150", "fontSize": 14, "textAlign": "center" },
    { "type": "text", "x": 720, "y": 490,
      "width": 220, "height": 30,
      "text": "Q3", "fontSize": 14, "textAlign": "center" }
  ]
}
```

坐标推导验证：
- bar-0 (120): height = (120/200)*400 = 240, y = 480-240 = 240
- bar-1 (200): height = (200/200)*400 = 400, y = 480-400 = 80
- bar-2 (150): height = (150/200)*400 = 300, y = 480-300 = 180
- bar-0 x = 80 + 0*300 + 80/2 = 120, bar-1 x = 80 + 1*300 + 40 = 420, bar-2 x = 80 + 2*300 + 40 = 720

## 陷阱

- 单系列用多色（不专业）：同一数据系列所有柱体应使用同一颜色
- 缺 Y 轴单位标注，读者无法理解数值含义
- 柱体间距不均匀（脚本需统一计算 barGap）
- Y 轴刻度线和格线误带箭头
- 坐标轴忘记带箭头
