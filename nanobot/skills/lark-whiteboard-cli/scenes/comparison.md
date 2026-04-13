# 对比图 / 矩阵图

适用于：方案对比、功能矩阵、技术选型等多选项按多维度比较的场景。

## Content 约束

- **每格内容要充实**：不要只写一个关键词，给出具体说明（如"MVCC 多版本并发控制，支持行级锁"而非仅"支持"）
- 单格内容不同格子允许不同长度，但每格不超过 5 行
- 长文本（超过 15 字）用 `textAlign: "left"`（不要居中）
- 第一行是标题行（对象名称），第一列是维度标签列
- 维度数量至少 4 个，充分展开对比维度

## Layout 选型

| 模式 | 适用条件 | 特征 |
|------|---------|------|
| **严格 grid（默认）** | 所有对比场景 | 表头行 + 数据行，每行 horizontal frame，行内 rect 等分 |
| **卡片式对比（替代）** | 维度较少（2-3 个） | 每个对象做一张独立卡片，卡片内纵向列出各维度。卡片横向等分：外层 `layout: "horizontal"`，每张卡片 `width: "fill-container"` |

## Layout 规则

- 最外层 frame：`layout: "vertical"`，固定 `width`（如 1000），`height: "fit-content"`
- 每行：horizontal frame，`width: "fill-container"`，`alignItems: "stretch"`
- 行内单元格全部 `width: "fill-container"` 等分列宽
- 行间 `gap >= 12`（不要 8，太紧）
- 行内列间 `gap: 8-12`
- 标题行：深色底白字（由 style 控制具体颜色）
- 每列同色边框保持视觉一致性
- 单元格 `height: "fit-content"`，不要写固定 height

## 骨架示例

### 3 列 4 行表格

```json
{
  "version": 2,
  "nodes": [
    {
      "type": "frame",
      "width": 1000,
      "height": "fit-content",
      "layout": "vertical",
      "gap": 12,
      "padding": 0,
      "children": [
        {
          "type": "text",
          "id": "title",
          "width": "fill-container",
          "height": "fit-content",
          "text": "[对比图标题]",
          "fontSize": 24,
          "textAlign": "center",
          "verticalAlign": "middle"
        },
        {
          "type": "frame",
          "id": "header-row",
          "width": "fill-container",
          "height": "fit-content",
          "layout": "horizontal",
          "gap": 8,
          "padding": 0,
          "alignItems": "stretch",
          "children": [
            { "type": "rect", "id": "h-dim", "width": "fill-container", "height": "fit-content", "text": "[维度]", "fontSize": 15, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 0, "borderWidth": 2 },
            { "type": "rect", "id": "h-col-1", "width": "fill-container", "height": "fit-content", "text": "[对象A]", "fontSize": 15, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "h-col-2", "width": "fill-container", "height": "fit-content", "text": "[对象B]", "fontSize": 15, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "h-col-3", "width": "fill-container", "height": "fit-content", "text": "[对象C]", "fontSize": 15, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 }
          ]
        },
        {
          "type": "frame",
          "id": "data-row-1",
          "width": "fill-container",
          "height": "fit-content",
          "layout": "horizontal",
          "gap": 8,
          "padding": 0,
          "alignItems": "stretch",
          "children": [
            { "type": "rect", "id": "d1-dim", "width": "fill-container", "height": "fit-content", "text": "[维度1]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "d1-c1", "width": "fill-container", "height": "fit-content", "text": "[...]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "d1-c2", "width": "fill-container", "height": "fit-content", "text": "[...]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "d1-c3", "width": "fill-container", "height": "fit-content", "text": "[...]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 }
          ]
        },
        {
          "type": "frame",
          "id": "data-row-2",
          "width": "fill-container",
          "height": "fit-content",
          "layout": "horizontal",
          "gap": 8,
          "padding": 0,
          "alignItems": "stretch",
          "children": [
            { "type": "rect", "id": "d2-dim", "width": "fill-container", "height": "fit-content", "text": "[维度2]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "d2-c1", "width": "fill-container", "height": "fit-content", "text": "[...]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "d2-c2", "width": "fill-container", "height": "fit-content", "text": "[...]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "d2-c3", "width": "fill-container", "height": "fit-content", "text": "[...]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 }
          ]
        },
        {
          "type": "frame",
          "id": "data-row-3",
          "width": "fill-container",
          "height": "fit-content",
          "layout": "horizontal",
          "gap": 8,
          "padding": 0,
          "alignItems": "stretch",
          "children": [
            { "type": "rect", "id": "d3-dim", "width": "fill-container", "height": "fit-content", "text": "[维度3]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "d3-c1", "width": "fill-container", "height": "fit-content", "text": "[...]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "d3-c2", "width": "fill-container", "height": "fit-content", "text": "[...]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 },
            { "type": "rect", "id": "d3-c3", "width": "fill-container", "height": "fit-content", "text": "[...]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle", "borderRadius": 8, "borderWidth": 2 }
          ]
        }
      ]
    }
  ]
}
```

## 陷阱

- **行间距 8px 太紧**：行间 gap 至少 12，8 会让行与行视觉粘连。
- **长文本居中对齐**：超过一行的文本应改为 `textAlign: "left"`，居中多行文本可读性差。
- **列数太多导致每列太窄**：对比对象建议 ≤ 5 列（含维度列），超过时合并维度或拆分为多张表。
- **列宽不等**：所有数据列必须用 `width: "fill-container"` 等分，不要给某列写固定宽度。
- **行高不等**：每行 frame 必须 `alignItems: "stretch"`，否则同行单元格因文字行数不同高矮不齐。
- **忘记维度标签列**：第一列放维度名称，标题行（维度列）用与数据列不同的视觉处理。
- **单元格用固定 height**：单元格必须 `height: "fit-content"`，固定高度会导致文字截断。
