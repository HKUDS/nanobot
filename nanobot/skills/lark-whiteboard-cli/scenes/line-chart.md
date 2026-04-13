# 折线图

## Content 约束

- 数据点 ≤ 15
- Y 轴必须有单位标注（如 "万元"、"%"）
- 折线系列 ≤ 3（超过太密看不清）

## Layout 选型

- **脚本生成坐标**（推荐）：用 .js 脚本计算数据点坐标和折线路径，脚本输出 JSON 文件后调用 `npx -y @larksuite/whiteboard-cli@^0.2.0` 渲染

## Layout 规则

- 白板坐标系 Y 轴向下为正，图表"底部原点"拥有最大 Y 值，数据点向上分布时 Y 减小
- 数据点用小 ellipse 标记（width: 12, height: 12）
- 折线用 connector straight 连接相邻数据点，endArrow: "none"
- 坐标轴用 connector 直线，末端带箭头（endArrow: "arrow"）
- 格线用虚线 connector（lineStyle: "dashed"，endArrow: "none"）
- 刻度线短横线 connector（endArrow: "none"）
- 数值标注放在数据点上方
- 类别标签放在 X 轴下方，居中对齐数据点

## 坐标与尺寸计算指南

白板坐标系中，**X 轴向右为正，Y 轴向下为正**。图表的"底部原点"拥有最大的 Y 坐标，数据点向上分布时 Y 坐标减小。

1. **确定图表区域**：
   - 设定图表区高度 `chartHeight` 和宽度 `chartWidth`
   - 设定左下角坐标原点 `(originX, originY)`
   - 示例：originX=80, originY=480, chartWidth=900, chartHeight=400
2. **Y 轴范围自适应**：
   - 找出数据最小值 `dataMin` 和最大值 `dataMax`
   - yMin 不一定为 0：若数据集中在 80-120，Y 轴从 0 开始会让折线挤在顶部一小段区域
   - 推荐：yMin = 向下取整到合适刻度（如 dataMin=82 → yMin=80），yMax = 向上取整（如 dataMax=118 → yMax=120）
   - 当数据波动极小时（如 98-102），适当扩大范围避免折线过于平坦
3. **数据点坐标计算**：
   - X 坐标：在可用宽度内均匀分布。`pointX = originX + (i / (pointCount - 1)) * chartWidth`
   - Y 坐标：按比例映射到高度。`pointY = originY - ((value - yMin) / (yMax - yMin)) * chartHeight`
   - ellipse 定位：`ellipseX = pointX - 6, ellipseY = pointY - 6`（圆心对齐数据点）
4. **连线逻辑**：
   - 用 connector straight 将相邻数据点连接
   - `from` = 点[i] 的 (pointX, pointY)，`to` = 点[i+1] 的 (pointX, pointY)
   - startArrow: "none", endArrow: "none"
5. **Y 轴刻度计算**：
   - 将 yMin 到 yMax 等分为 4-5 个刻度
   - 每个刻度的 Y 坐标：`gridY = originY - ((tickValue - yMin) / (yMax - yMin)) * chartHeight`

## 完整 JSON 示例

以下示例：4 个数据点，数据 [120, 200, 150, 180]，yMin=100, yMax=220，originX=80, originY=480, chartWidth=900, chartHeight=400。

- 刻度：100, 130, 160, 190, 220（每 30 一格）
- 点0 (120): pointX=80, pointY=480-((120-100)/120)*400=480-66.7=413
- 点1 (200): pointX=80+300=380, pointY=480-((200-100)/120)*400=480-333.3=147
- 点2 (150): pointX=80+600=680, pointY=480-((150-100)/120)*400=480-166.7=313
- 点3 (180): pointX=80+900=980, pointY=480-((180-100)/120)*400=480-266.7=213

```json
{
  "version": 2,
  "nodes": [
    { "type": "rect", "x": 0, "y": 0, "width": 1100, "height": 580 },

    { "type": "text", "x": 80, "y": 10, "width": 900, "height": "fit-content",
      "text": "季度销售额趋势", "fontSize": 24, "textAlign": "center" },

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
      "text": "100", "fontSize": 12, "textAlign": "right" },

    { "type": "connector", "connector": {
      "from": { "x": 70, "y": 380 }, "to": { "x": 80, "y": 380 },
      "lineShape": "straight", "lineWidth": 1,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "text", "x": 20, "y": 370, "width": 50, "height": 20,
      "text": "130", "fontSize": 12, "textAlign": "right" },
    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 380 }, "to": { "x": 980, "y": 380 },
      "lineShape": "straight", "lineWidth": 1, "lineStyle": "dashed",
      "startArrow": "none", "endArrow": "none"
    }},

    { "type": "connector", "connector": {
      "from": { "x": 70, "y": 280 }, "to": { "x": 80, "y": 280 },
      "lineShape": "straight", "lineWidth": 1,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "text", "x": 20, "y": 270, "width": 50, "height": 20,
      "text": "160", "fontSize": 12, "textAlign": "right" },
    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 280 }, "to": { "x": 980, "y": 280 },
      "lineShape": "straight", "lineWidth": 1, "lineStyle": "dashed",
      "startArrow": "none", "endArrow": "none"
    }},

    { "type": "connector", "connector": {
      "from": { "x": 70, "y": 180 }, "to": { "x": 80, "y": 180 },
      "lineShape": "straight", "lineWidth": 1,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "text", "x": 20, "y": 170, "width": 50, "height": 20,
      "text": "190", "fontSize": 12, "textAlign": "right" },
    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 180 }, "to": { "x": 980, "y": 180 },
      "lineShape": "straight", "lineWidth": 1, "lineStyle": "dashed",
      "startArrow": "none", "endArrow": "none"
    }},

    { "type": "connector", "connector": {
      "from": { "x": 70, "y": 80 }, "to": { "x": 80, "y": 80 },
      "lineShape": "straight", "lineWidth": 1,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "text", "x": 20, "y": 70, "width": 50, "height": 20,
      "text": "220", "fontSize": 12, "textAlign": "right" },
    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 80 }, "to": { "x": 980, "y": 80 },
      "lineShape": "straight", "lineWidth": 1, "lineStyle": "dashed",
      "startArrow": "none", "endArrow": "none"
    }},

    { "type": "connector", "connector": {
      "from": { "x": 80, "y": 413 }, "to": { "x": 380, "y": 147 },
      "lineShape": "straight", "lineWidth": 3,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "connector", "connector": {
      "from": { "x": 380, "y": 147 }, "to": { "x": 680, "y": 313 },
      "lineShape": "straight", "lineWidth": 3,
      "startArrow": "none", "endArrow": "none"
    }},
    { "type": "connector", "connector": {
      "from": { "x": 680, "y": 313 }, "to": { "x": 980, "y": 213 },
      "lineShape": "straight", "lineWidth": 3,
      "startArrow": "none", "endArrow": "none"
    }},

    { "type": "ellipse", "id": "pt-0", "x": 74, "y": 407,
      "width": 12, "height": 12 },
    { "type": "text", "x": 55, "y": 383,
      "width": 50, "height": 20,
      "text": "120", "fontSize": 14, "textAlign": "center" },
    { "type": "text", "x": 50, "y": 490,
      "width": 60, "height": 30,
      "text": "Q1", "fontSize": 14, "textAlign": "center" },

    { "type": "ellipse", "id": "pt-1", "x": 374, "y": 141,
      "width": 12, "height": 12 },
    { "type": "text", "x": 355, "y": 117,
      "width": 50, "height": 20,
      "text": "200", "fontSize": 14, "textAlign": "center" },
    { "type": "text", "x": 350, "y": 490,
      "width": 60, "height": 30,
      "text": "Q2", "fontSize": 14, "textAlign": "center" },

    { "type": "ellipse", "id": "pt-2", "x": 674, "y": 307,
      "width": 12, "height": 12 },
    { "type": "text", "x": 655, "y": 283,
      "width": 50, "height": 20,
      "text": "150", "fontSize": 14, "textAlign": "center" },
    { "type": "text", "x": 650, "y": 490,
      "width": 60, "height": 30,
      "text": "Q3", "fontSize": 14, "textAlign": "center" },

    { "type": "ellipse", "id": "pt-3", "x": 974, "y": 207,
      "width": 12, "height": 12 },
    { "type": "text", "x": 955, "y": 183,
      "width": 50, "height": 20,
      "text": "180", "fontSize": 14, "textAlign": "center" },
    { "type": "text", "x": 950, "y": 490,
      "width": 60, "height": 30,
      "text": "Q4", "fontSize": 14, "textAlign": "center" }
  ]
}
```

坐标推导验证：
- 点0 (Q1, 120): pointX = 80 + (0/3)*900 = 80, pointY = 480 - ((120-100)/120)*400 = 413
- 点1 (Q2, 200): pointX = 80 + (1/3)*900 = 380, pointY = 480 - ((200-100)/120)*400 = 147
- 点2 (Q3, 150): pointX = 80 + (2/3)*900 = 680, pointY = 480 - ((150-100)/120)*400 = 313
- 点3 (Q4, 180): pointX = 80 + (3/3)*900 = 980, pointY = 480 - ((180-100)/120)*400 = 213
- ellipse 定位：ellipseX = pointX - 6, ellipseY = pointY - 6

## 陷阱

- Y 轴范围不合理：若数据集中在 80-120，Y 轴从 0 到 120 会让折线挤在顶部一小段区域，应设 yMin 接近数据最小值
- 缺 Y 轴单位标注，读者无法理解数值含义
- 数据点太密时标注互相遮挡（超过 10 个点考虑隔一个标注一次）
- 折线段忘记设 endArrow: "none"，默认带箭头
- 多系列时折线颜色相近难以区分，应使用对比度高的不同色系
