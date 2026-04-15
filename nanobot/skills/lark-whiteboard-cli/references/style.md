# 配色系统

## 怎么上色（最重要）

上色步骤：

1. **找出图中有几个分组**（层级、分支、类别、阶段...）
2. **为每个分组选一种不同颜色**（从色板中选 2-4 种颜色）
3. **分组容器**用浅色填充 — 告诉读者"这块是一个整体"
4. **分组内节点**用白色填充 + 该分组的深色 borderColor — 告诉读者"这些属于这个分组"

具体映射（经典色板）：

| 分组 | 层容器 fillColor | 层容器 borderColor | 内部节点 borderColor |
|------|----------------|-------------------|---------------------|
| 第 1 组 | #F0F4FC（浅蓝） | #5178C6 | #5178C6 |
| 第 2 组 | #EAE2FE（浅紫） | #8569CB | #8569CB |
| 第 3 组 | #DFF5E5（浅绿） | #509863 | #509863 |
| 第 4 组 | #FEF1CE（浅黄） | #D4B45B | #D4B45B |
| 第 5 组 | #FEE3E2（浅红） | #D25D5A | #D25D5A |
| 内部节点 | #FFFFFF | 跟随所属分组 | — |

**各类图表怎么上色**：
- 架构图有 3 层 → 每层一种颜色，层背景浅色填充，层内节点白色+深色边框
- 对比表有 3 列 → 每列表头一种颜色，该列数据单元格用同色边框
- 组织架构有 4 个部门 → 每个部门一种颜色，子部门白色+同色边框
- 流程图 → 起止节点一种颜色，判断节点一种颜色，步骤节点白色

> [!IMPORTANT]
> **用户配色优先。** 用户指定了色值/风格时以用户为准。用户只给 1-2 个色值时，推导完整色板：主色→浅底→深边框→灰调连线色。
> 用户**未指定**配色时，必须从上方色板表中选取颜色，不要使用表中没有的自创色值（如 `#E8F3FF`、`#1664FF`、`#14C9C9` 等都不在色板中）。

---

## 结构规则

### 分组 — 不同层/分组必须用不同颜色

选 2-4 种颜色，每种代表一个分组。同组节点视觉完全一致（fillColor、borderColor 相同）。

### 分层 — 外重内轻

- 外层（大分区）：浅色填充背景
- 内层（具体节点）：白色填充 + 分组色边框

### 清晰

- 所有节点有边框（borderWidth=2）
- 间距不粘连（gap >= 8，有连线时 >= 40）
- 文字在背景上清晰可读（fontSize >= 14）。文字与背景色对比度应足够（参考 WCAG 2.1：正文至少 4.5:1，标题至少 3:1）
- 不要仅靠颜色区分信息——同时使用边框、形状或文字标签辅助，确保色觉障碍用户也能理解
- 连线用灰色（#BBBFC4），不抢节点注意力

### 统一参数

| 参数 | 值 | 为什么 |
|------|---|--------|
| borderWidth | 2 | 让边框清晰可见 |
| borderRadius | 8 | 统一的圆角，整洁 |
| gap（最小值） | 8 | 元素不粘连 |
| padding（最小值） | 8 | 内容不贴边 |
| gap（有连线时） | 40 | 给箭头留空间 |
| fontSize（正文） | >= 14 | 可读 |
| fontSize（标题） | >= 24 | 醒目 |
| fontSize（辅助） | >= 13 | 不费眼 |

---

## 色板选择指南

根据用户需求的关键词或场景选择合适的色板。未指定时默认使用"经典"色板。

| 色板 | 适用场景 | 关键词 |
|------|---------|-------|
| 经典 | 通用图表、说明文档 | 默认、通用 |
| 商务 | 汇报、企业架构、正式文档 | 专业、正式、给老板看 |
| 科技 | 技术架构、DevOps、监控 | 技术、炫酷、暗色 |
| 清新 | 流程图、用户旅程、教程 | 清新、自然、轻松 |
| 极简 | 论文配图、学术报告 | 学术、极简、黑白 |

---

## 预设色板

每套色板定义 7 个角色的颜色。**连线色是色板的一部分**，不同色板的连线色不同。

### 经典

| 角色 | fillColor | borderColor | textColor |
|------|-----------|-------------|-----------|
| 分区背景 | #F0F4FC | #5178C6 | #1F2329 |
| 分组标题 | #EAE2FE | #8569CB | #1F2329 |
| 内容节点 | #FFFFFF | #5178C6 | #1F2329 |
| 第二分组 | #DFF5E5 | #509863 | #1F2329 |
| 第三分组 | #FEF1CE | #D4B45B | #1F2329 |
| 第四分组 | #FEE3E2 | #D25D5A | #1F2329 |
| 强调/表头 | #1F2329 | #1F2329 | #FFFFFF |
| 连线 | -- | -- | #BBBFC4 |

### 商务

| 角色 | fillColor | borderColor | textColor |
|------|-----------|-------------|-----------|
| 分区背景 | #EDF2F7 | #4A6FA5 | #1A202C |
| 分组标题 | #D4E0ED | #4A6FA5 | #1A202C |
| 内容节点 | #FFFFFF | #718BAE | #1A202C |
| 第二分组 | #E8EDF3 | #5A7B9A | #1A202C |
| 第三分组 | #F0F0F0 | #8895A7 | #1A202C |
| 强调/表头 | #2D4A7A | #2D4A7A | #FFFFFF |
| 连线 | -- | -- | #718BAE |

### 科技

| 角色 | fillColor | borderColor | textColor |
|------|-----------|-------------|-----------|
| 画布/分区背景 | #0F172A | #1E293B | #E2E8F0 |
| 分组标题 | #1E293B | #3B82F6 | #E2E8F0 |
| 内容节点 | #1E293B | #334155 | #E2E8F0 |
| 第二分组 | #1E293B | #8B5CF6 | #E2E8F0 |
| 第三分组 | #1E293B | #10B981 | #E2E8F0 |
| 强调 | #2563EB | #3B82F6 | #FFFFFF |
| 连线 | -- | -- | #475569 |

### 清新

| 角色 | fillColor | borderColor | textColor |
|------|-----------|-------------|-----------|
| 分区背景 | #F0FDF4 | #86EFAC | #14532D |
| 分组标题 | #DCFCE7 | #4ADE80 | #14532D |
| 内容节点 | #FFFFFF | #86EFAC | #14532D |
| 第二分组 | #ECFDF5 | #6EE7B7 | #14532D |
| 第三分组 | #F0FDFA | #5EEAD4 | #134E4A |
| 强调 | #16A34A | #16A34A | #FFFFFF |
| 连线 | -- | -- | #86EFAC |

### 极简

| 角色 | fillColor | borderColor | textColor |
|------|-----------|-------------|-----------|
| 分区背景 | #F8F9FA | #DEE2E6 | #212529 |
| 分组标题 | #E9ECEF | #ADB5BD | #212529 |
| 内容节点 | #FFFFFF | #CED4DA | #212529 |
| 第二分组 | #F1F3F5 | #868E96 | #212529 |
| 第三分组 | #F8F9FA | #ADB5BD | #212529 |
| 强调/表头 | #495057 | #495057 | #FFFFFF |
| 连线 | -- | -- | #ADB5BD |

---

## 各元素怎么画

> 以下示例使用经典色板。如果选了其他色板，替换对应颜色即可，结构保持不变。

### 图表标题

告诉读者"这张图讲什么"。大号深色文字，居中。

```json
{ "type": "text", "fontSize": 24, "textColor": "#1F2329", "textAlign": "center" }
```

### 分区背景

把相关的内容圈在一起，告诉读者"这些属于同一个大类"。浅色做 fillColor，对应深色做 borderColor。内部放白色节点。

```json
{ "fillColor": "#F0F4FC", "borderColor": "#5178C6", "borderWidth": 2, "borderRadius": 8, "padding": 20 }
```

### 分区标签

给分区一个名字。用独立 text 节点，不要用 frame 的 `title` 属性（会被渲染为极小标题栏）。

**所有分区标签统一用深色文字 `#1F2329`**，不要给每个标签用不同颜色——颜色区分通过层容器背景和边框体现，标签文字颜色保持一致。

```json
{ "type": "text", "width": 180, "height": "fit-content", "text": "Access layer", "fontSize": 20, "textColor": "#1F2329", "textAlign": "right" }
```

### 分组标题

告诉读者"这个子分组叫什么"。色板色填充 + 同色系深色边框。

```json
{ "fillColor": "#EAE2FE", "borderColor": "#8569CB", "borderWidth": 2, "borderRadius": 8, "fontSize": 14, "textColor": "#1F2329" }
```

### 内容节点

具体的信息项。白色填充，边框颜色跟随所属分组。

```json
{ "fillColor": "#FFFFFF", "borderColor": "#5178C6", "borderWidth": 2, "borderRadius": 8, "fontSize": 14, "textColor": "#1F2329" }
```

白色节点的 borderColor 取决于它所属的分组：
```
属于蓝色分组: fillColor="#FFFFFF"  borderColor="#5178C6"  borderWidth=2
属于紫色分组: fillColor="#FFFFFF"  borderColor="#8569CB"  borderWidth=2
独立节点:     fillColor="#FFFFFF"  borderColor="#DEE0E3"  borderWidth=2
```
（注：以上为经典色板的值，其他色板替换对应的 borderColor）

### 表头

告诉读者"这一列/行是什么维度"。深色填充 + 白色文字。

```json
{ "fillColor": "#1F2329", "borderColor": "#1F2329", "borderWidth": 2, "borderRadius": 0, "fontSize": 15, "textColor": "#FFFFFF", "textAlign": "center" }
```

### 图标组件

icon + text 的组合卡片。icon 的 `color` 跟随所属分组的 borderColor，与其他节点视觉一致。

```json
{
  "type": "frame", "layout": "vertical", "gap": 4, "padding": 12,
  "alignItems": "center", "fillColor": "#FFFFFF", "borderColor": "#5178C6", "borderWidth": 2, "borderRadius": 8,
  "children": [
    { "type": "icon", "name": "server", "width": 36, "height": 36, "color": "#5178C6" },
    { "type": "text", "width": "fit-content", "height": "fit-content", "text": "应用服务器", "fontSize": 12 }
  ]
}
```

icon color 需要结合上下文选择合适的颜色, 比如: 使用所属分组的borderColor

### textColor 规则

```
- 正文：#1F2329（深色，在白底/浅色底上清晰）
- 辅助说明：#646A73（弱化，不抢注意力）
- 深色底上：#FFFFFF（反色，清晰可读）
（以上为经典色板的值，其他色板参考对应 textColor 列）
```

### 辅助说明

补充信息，不抢主角的注意力。灰色小字。

```json
{ "fontSize": 13, "textColor": "#646A73" }
```

### 连线

表达元素之间的关系或流向。使用色板中的连线色。

```json
{ "lineColor": "#BBBFC4", "lineWidth": 2 }
```

### 布局容器

纯粹用来排版的 frame，读者看不见它。不设 fillColor、borderColor。

```json
{ "type": "frame", "layout": "vertical", "gap": 28, "padding": 32 }
```

### 分组容器

用虚线框圈定一组节点，比分区背景更轻量。

```json
{ "borderColor": "#DEE0E3", "borderWidth": 2, "borderDash": "dashed", "borderRadius": 8 }
```

---

## 常见错误

错误：每个节点一种颜色 -> 读者分不清谁和谁是一组
```json
{ "fillColor": "#8569CB" }, { "fillColor": "#5178C6" }, { "fillColor": "#509863" }
```
正确：同组节点视觉一致 -> 读者一眼看出关系
```json
{ "fillColor": "#FFFFFF", "borderColor": "#8569CB" }, { "fillColor": "#FFFFFF", "borderColor": "#8569CB" }
```

错误：内外层都用重色 -> 读者不知道先看哪里
```json
{ "type": "frame", "fillColor": "#5178C6", "children": [{ "fillColor": "#8569CB" }] }
```
正确：外层浅色内层白色 -> 读者先看结构再看细节
```json
{ "type": "frame", "fillColor": "#F0F4FC", "children": [{ "fillColor": "#FFFFFF", "borderColor": "#5178C6" }] }
```

错误：连线用和节点一样的彩色 -> 和节点颜色抢注意力
```json
{ "connector": { "lineColor": "#5178C6" } }
```
正确：连线用色板中的连线色 -> 衬托节点
```json
{ "connector": { "lineColor": "#BBBFC4" } }
```

错误：节点没边框 -> 和背景融为一体，看不清边界
```json
{ "fillColor": "#FFFFFF" }
```
正确：节点有边框 -> 边界清晰
```json
{ "fillColor": "#FFFFFF", "borderColor": "#DEE0E3", "borderWidth": 2 }
```

错误：全图黑白灰，没有颜色区分 -> 读者无法快速识别分组
```json
{ "fillColor": "#FFFFFF", "borderColor": "#DEE0E3" }
```
正确：不同分组用不同颜色 -> 一眼看出结构（蓝色分组 + 紫色分组）
```json
{ "fillColor": "#F0F4FC", "borderColor": "#5178C6" }
{ "fillColor": "#EAE2FE", "borderColor": "#8569CB" }
```
