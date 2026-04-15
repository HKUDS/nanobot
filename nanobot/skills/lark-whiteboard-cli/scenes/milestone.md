# 里程碑时间线 (Milestone)

## Content 约束

- 节点 4-8 个
- 每节点：标题 + 日期 + 可选描述
- 时间从左到右递增

## Layout 选型

两种方案按需选择：

1. **横向时间线**：horizontal frame，节点等分
2. **交替上下**：绝对定位，节点交替在时间轴上下方（节点多时更紧凑）

## 结构特征

- **标题居中**：顶部放置图表标题
- **年份/时间轴条**：箭头形色块承载年份，按时间从左到右递增
- **里程碑卡片**：下方虚线圆角卡片承载标题与描述
- **严格对齐**：年份条与对应卡片等宽，左右对齐
- **文字层级**：标题加粗在上，描述文字更小更浅在下，居中对齐

## Layout 规则

- 绝对定位为主（`layout: "none"`），节点位置承载时间序列含义
- 先确定里程碑数量，计算等距的 x 坐标序列
- 时间轴用 connector 贯穿所有节点
- 节点与时间轴用短竖线连接
- 节点间水平间距一致
- 年份条宽度 = 卡片宽度，垂直间距统一
- 标题与年份区域保留足够留白

## 骨架示例

```json
{
  "version": 2,
  "nodes": [
    {
      "type": "frame",
      "x": 0, "y": 0,
      "width": 1200, "height": 360,
      "layout": "none",
      "children": [
        {
          "type": "text",
          "x": 300, "y": 12,
          "width": 600, "height": "fit-content",
          "text": [{ "content": "{{CHART_TITLE}}", "bold": true, "fontSize": 24 }],
          "textAlign": "center"
        },

        {
          "type": "svg",
          "x": 50, "y": 56,
          "width": 190, "height": 36,
          "svg": {
            "code": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 190 36\"><polygon points=\"0,0 170,0 190,18 170,36 0,36\"/></svg>"
          }
        },
        {
          "type": "text",
          "x": 50, "y": 64,
          "width": 190, "height": "fit-content",
          "text": "{{DATE_1}}",
          "textAlign": "center"
        },
        {
          "type": "rect",
          "x": 50, "y": 132,
          "width": 190, "height": 120,
          "borderDash": "dashed",
          "borderRadius": 8
        },
        {
          "type": "text",
          "x": 50, "y": 150,
          "width": 190, "height": "fit-content",
          "text": [{ "content": "{{MILESTONE_1_TITLE}}", "bold": true, "fontSize": 16 }],
          "textAlign": "center"
        },
        {
          "type": "text",
          "x": 50, "y": 180,
          "width": 190, "height": "fit-content",
          "text": "{{MILESTONE_1_DESC}}",
          "fontSize": 13,
          "textAlign": "center"
        },

        {
          "type": "svg",
          "x": 290, "y": 56,
          "width": 190, "height": 36,
          "svg": {
            "code": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 190 36\"><polygon points=\"0,0 170,0 190,18 170,36 0,36\"/></svg>"
          }
        },
        {
          "type": "text",
          "x": 290, "y": 64,
          "width": 190, "height": "fit-content",
          "text": "{{DATE_2}}",
          "textAlign": "center"
        },
        {
          "type": "rect",
          "x": 290, "y": 132,
          "width": 190, "height": 120,
          "borderDash": "dashed",
          "borderRadius": 8
        },
        {
          "type": "text",
          "x": 290, "y": 150,
          "width": 190, "height": "fit-content",
          "text": [{ "content": "{{MILESTONE_2_TITLE}}", "bold": true, "fontSize": 16 }],
          "textAlign": "center"
        },
        {
          "type": "text",
          "x": 290, "y": 180,
          "width": 190, "height": "fit-content",
          "text": "{{MILESTONE_2_DESC}}",
          "fontSize": 13,
          "textAlign": "center"
        }
      ]
    }
  ]
}
```

## 陷阱

- **节点太多时太拥挤**：超过 6 个节点时考虑交替上下布局或增大画布宽度
- **右侧节点与时间轴末端重叠**：最后一个节点的 x + width 不要超出画布边界
- **年份条与卡片不对齐**：年份条和卡片的 x、width 必须完全一致
