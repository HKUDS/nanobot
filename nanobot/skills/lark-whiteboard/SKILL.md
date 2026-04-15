---
name: lark-whiteboard
version: 1.0.0
description: >
  飞书画板：查询和编辑飞书云文档中的画板。支持导出画板为预览图片、导出原始节点结构、使用 PlantUML/Mermaid 代码或 OpenAPI 原生格式更新画板内容。
  当用户需要查看画板内容、导出画板图片、或编辑画板，或是需要可视化表达架构、流程、组织关系、时间线、因果、对比等结构化信息时使用此 skill，无论是否提及"画板"。
metadata:
  requires:
    bins: [ "lark-cli" ]
  cliHelp: "lark-cli whiteboard --help"
---

# whiteboard (v1)

**CRITICAL — 开始前 MUST 先用 Read 工具读取 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)，其中包含认证、权限处理**

## 核心概念

### 画板 Token

画板 token 是画板的唯一标识符。飞书画板嵌入在云文档中，可以从云文档的 `docs +fetch` 结果中获取（`<whiteboard token="xxx"/>`
标签），或从 `docs +update` 新建画板后的 `data.board_tokens` 字段中获取。

## 快速决策

当需要插入图表时：

1. 能否使用飞书画板？
    - 能 → 走画板路径（推荐！可编辑、可协作）
    - 不能 → 走图片路径

| 用户需求                             | 推荐 Shortcut                                                                                                                                            |
|----------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| "查看这个画板的内容"                      | [`+query --output_as image`](references/lark-whiteboard-query.md)                                                                                      |
| "导出画板为图片"                        | [`+query --output_as image`](references/lark-whiteboard-query.md)                                                                                      |
| "获取画板的 PlantUML/Mermaid 代码"      | [`+query --output_as code`](references/lark-whiteboard-query.md)                                                                                       |
| "检查画板是否由 PlantUML/Mermaid 代码块组成" | [`+query --output_as code`](references/lark-whiteboard-query.md)                                                                                       |
| "修改画板某个节点的颜色或文字"                 | [`+query --output_as raw`](references/lark-whiteboard-query.md) 后 [`+update`](references/lark-whiteboard-update.md)                                    |
| "用 PlantUML 绘制画板"                | [`+update --input_format plantuml`](references/lark-whiteboard-update.md)                                                                              |
| "用 Mermaid 绘制画板"                 | [`+update --input_format mermaid`](references/lark-whiteboard-update.md)                                                                               |
| "在画板绘制复杂图表"                      | [`+update --input_format raw`](references/lark-whiteboard-update.md), 需要使用 whiteboard-cli 工具，参见 [lark-whiteboard-cli](../lark-whiteboard-cli/SKILL.md) |

## Shortcuts

| Shortcut                                          | 说明                                          |
|---------------------------------------------------|---------------------------------------------|
| [`+query`](references/lark-whiteboard-query.md)   | 查询画板，导出为预览图片、代码或原始节点结构                      |
| [`+update`](references/lark-whiteboard-update.md) | 更新画板内容，支持 PlantUML、Mermaid 或 OpenAPI 原生格式输入 |

## Workflow

### 场景 1: 创作一个画板

1. 确定需要创作的画板 Token（从用户请求或对应的文档中获取）与要创作的内容
2. 参考 [lark-whiteboard-cli](../lark-whiteboard-cli/SKILL.md) 生成画板内容
3. 使用 [`+update`](references/lark-whiteboard-update.md) shortcut 更新画板内容

### 场景 2: 修改或优化一个画板

1. 确定要修改的画板 Token （从用户请求或对应的文档中获取）
2. 使用 [`+query --output_as code`](references/lark-whiteboard-query.md) shortcut 导出画板代码，确认画板是否由 Mermaid 或
   PlantUML 绘制
    1. 如果 +query --output_as code 返回了 Mermaid / PlantUML 代码块，则在这一代码的基础上优化修改
    2. 如果没有返回代码块，则使用 [`+query --output_as image`](references/lark-whiteboard-query.md)
       获取画板预览图片，根据图片内容参考 [lark-whiteboard-cli](../lark-whiteboard-cli/SKILL.md) 重绘优化
    3. 如果用户只需要简单修改某个节点的文本内容/颜色，可以使用 [
       `+query --output_as raw`](references/lark-whiteboard-query.md) shortcut 导出画板原生 OpenAPI 格式，并在此基础上修改。
    4. 如果用户有明确要求，则以用户要求优先。
3. 使用 [`+update`](references/lark-whiteboard-update.md) shortcut 创建新的画板内容。根据用户需求，你可能会需要使用 [
   `docs +update`](../lark-doc/references/lark-doc-update.md) 创建新的画板，或使用 [
   `+update --overwrite`](references/lark-whiteboard-update.md) 在原画板上覆盖式更新。

## 与 lark-doc 的配合使用

### 场景 1: 从文档中获取画板 token

1. 使用 `lark-doc` 的 [`+fetch`](../lark-doc/references/lark-doc-fetch.md) 获取文档内容
2. 从返回的 markdown 中解析 `<whiteboard token="xxx"/>` 标签，记录画板 token
3. 使用本 skill 的 `+query` 或 `+update` 读取或操作画板

### 场景 2: 新建画板并编辑（完整流程）

这是最常见的使用场景，**必须完整执行以下步骤**：

1. 使用 `lark-doc` 的 [`+update`](../lark-doc/references/lark-doc-update.md) 创建空白画板
    - 在 markdown 中传入 `<whiteboard type="blank"></whiteboard>`
    - **注意这一 XML 标签不要转义**
    - 需要多个画板时，重复多个 whiteboard 标签

2. 从响应的 `data.board_tokens` 中获取新建画板的 token 列表
    - 记录每个 token 对应的图表类型和位置

3. 根据文档主题，为每个画板设计相应的内容
    - 参考下方"常见图表模板与参考指南"选择合适的语法
    - 使用 Mermaid（推荐）、PlantUML 或 [lark-whiteboard-cli](../lark-whiteboard-cli/SKILL.md) 生成内容

4. **逐个更新画板**：使用本 skill 的 `+update` shortcut 编辑每个画板的内容
    - 不要遗漏任何一个画板 token
    - 确保每个画板都有实际内容，不是空白

### 常见图表模板与参考指南

| 图表类型           | 推荐语法               | 详细参考指南                                                                                      |
|----------------|--------------------|---------------------------------------------------------------------------------------------|
| 架构图            | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/architecture.md](../lark-whiteboard-cli/scenes/architecture.md) |
| 流程图            | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/flowchart.md](../lark-whiteboard-cli/scenes/flowchart.md)       |
| 组织架构图          | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/organization.md](../lark-whiteboard-cli/scenes/organization.md) |
| 里程碑/时间线        | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/milestone.md](../lark-whiteboard-cli/scenes/milestone.md)       |
| 鱼骨图            | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/fishbone.md](../lark-whiteboard-cli/scenes/fishbone.md)         |
| 对比图            | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/comparison.md](../lark-whiteboard-cli/scenes/comparison.md)     |
| 飞轮图            | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/flywheel.md](../lark-whiteboard-cli/scenes/flywheel.md)         |
| 金字塔图           | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/pyramid.md](../lark-whiteboard-cli/scenes/pyramid.md)           |
| 思维导图/饼图/时序图/类图 | Mermaid            | [lark-whiteboard-cli/scenes/mermaid.md](../lark-whiteboard-cli/scenes/mermaid.md)           |
| 柱状图            | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/bar-chart.md](../lark-whiteboard-cli/scenes/bar-chart.md)       |
| 折线图            | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/line-chart.md](../lark-whiteboard-cli/scenes/line-chart.md)     |
| 树状图            | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/treemap.md](../lark-whiteboard-cli/scenes/treemap.md)           |
| 漏斗图            | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/funnel.md](../lark-whiteboard-cli/scenes/funnel.md)             |
| 泳道图            | whiteboard-cli DSL | [lark-whiteboard-cli/scenes/swimlane.md](../lark-whiteboard-cli/scenes/swimlane.md)         |
