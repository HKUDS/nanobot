# 系统架构图

适用于：分层架构图、微服务架构图、前后端架构图等有明确模块划分的场景。

## Content 约束

- **充分展开**：用户说"IM 架构"，要展开到接入层（Web/iOS/Android/桌面）、网关层（接入/路由/安全）、服务层（核心服务+支撑服务两个子区域）、存储层（MySQL/Redis/MongoDB + 括号说明用途）
- 每层节点 3-6 个。超过 6 个分两排或拆为子区域（如"核心服务"和"支撑服务"各一个子 frame）
- 层标签简短（2-4 字），如"接入层""网关层"
- 每个节点有标题 + 简短说明（如"用户服务\n注册登录和权限管理"）
- 技术组件加括号注明技术栈（如"消息队列\n(Kafka)"）
- 存储节点必须用 `cylinder` 类型（弧度固定 16px，禁止 `fill-container` 宽度，用 120-200 固定宽度）。每行最多 4 个 cylinder（超过 4 个换行或合并同类项，如多个 MySQL 合并为"关系数据库\n(MySQL)"）
- 侧边栏（如运维监控、基础设施）只在用户明确要求时才加，最多 2-3 项。不要自作主张添加侧边栏
- 可使用 icon+text 组合更直观的进行内容展示和增强辨识度
- **连线：非必要不画。** 架构图的分层结构本身已表达了调用方向（上层调下层），不需要每对节点都连线。只在需要强调特定调用关系时才画，且总数不超过 3-5 条

## Layout 选型

| 模式                 | 适用条件                                  | 特征                                                                                         |
| -------------------- | ----------------------------------------- | -------------------------------------------------------------------------------------------- |
| **grid（分层条带）** | 有明确上下层级关系（接入→网关→服务→存储） | 行=层级，每行 horizontal frame 等分节点。左侧 text 标签 + 右侧层 frame（Label-Outside 模式） |
| **grid（网格矩阵）** | 多模块平级，无明确层级                    | N×M 网格等分，每格一个模块                                                                   |
| **混合（岛屿式）**   | 模块间网状互联，无清晰分层                | 宏观 `layout: "none"` + x/y 定位各模块岛屿，微观每个岛屿内部用 flex 布局                     |

## Layout 规则

- **根节点**：固定宽度（1200），`height: "fit-content"`，`layout: "vertical"`，`gap: 20`，`padding: 24`
- **主体双栏**（有侧边栏时）：horizontal frame，`alignItems: "stretch"`，`gap: 16`
  - 左侧 layers-container：`width: "fill-container"`，vertical，`gap: 16`
  - 右侧 sidebar：固定宽度 160-180，`height: "fill-container"`，`justifyContent: "space-between"`
- **单层（Label-Outside）**：horizontal frame，左侧 text 标签（`width: 80`，`textAlign: "right"`），右侧层 frame（`fill-container`，带 borderWidth/borderRadius，`padding: 24`，`gap: 16`）。**为什么用 Label-Outside**：标签放在 frame 外部更简洁，避免在 frame 内部嵌套窄 rect 导致竖排文字和对齐问题。
- **子区域**：在层 frame 内嵌套 horizontal wrapper（`alignItems: "stretch"` 保证同行等高），内含多个 vertical frame（各子区域），每个子区域有自己的标题 text + 内容行。行内组件 `width: "fill-container"` 自动均分。
- **侧边栏**：拆成独立的逻辑块 frame（如"运维监控"和"基础设施"分开），各块 `height: "fill-container"`。外层 `justifyContent: "space-between"` 保证与左侧对齐，内部可设 `justifyContent: "center"` 使内容居中。
- **行内标签**：层内如有贯穿多列的特殊组件（如中间件），可采用"左侧小标签 + 右侧组件组"的横向布局

## 骨架示例

### 分层条带（Label-Outside + 侧边栏）

```json
{
  "version": 2,
  "nodes": [
    {
      "type": "frame",
      "id": "root",
      "x": 0, "y": 0,
      "width": 1200,
      "height": "fit-content",
      "layout": "vertical",
      "gap": 20,
      "padding": 24,
      "children": [
        {
          "type": "text",
          "id": "title",
          "width": "fill-container",
          "height": "fit-content",
          "text": "[图表标题]",
          "fontSize": 24,
          "textAlign": "center",
          "verticalAlign": "middle"
        },
        {
          "type": "frame",
          "id": "main-container",
          "width": "fill-container",
          "height": "fit-content",
          "layout": "horizontal",
          "alignItems": "stretch",
          "gap": 16,
          "padding": 0,
          "children": [
            {
              "type": "frame",
              "id": "layers-container",
              "width": "fill-container",
              "height": "fit-content",
              "layout": "vertical",
              "alignItems": "stretch",
              "gap": 16,
              "padding": 0,
              "children": [
                {
                  "type": "frame",
                  "id": "row-layer-1",
                  "width": "fill-container",
                  "height": "fit-content",
                  "layout": "horizontal",
                  "gap": 24,
                  "padding": 0,
                  "alignItems": "center",
                  "children": [
                    {
                      "type": "text",
                      "id": "label-1",
                      "width": 80,
                      "height": "fit-content",
                      "text": "[层标签]",
                      "fontSize": 20,
                      "textAlign": "right"
                    },
                    {
                      "type": "frame",
                      "id": "layer-1",
                      "width": "fill-container",
                      "height": "fit-content",
                      "borderWidth": 2,
                      "borderRadius": 8,
                      "layout": "horizontal",
                      "gap": 16,
                      "padding": 24,
                      "alignItems": "stretch",
                      "children": [
                        { "type": "rect", "id": "n-1-1", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                        { "type": "rect", "id": "n-1-2", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                        { "type": "rect", "id": "n-1-3", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" }
                      ]
                    }
                  ]
                },
                {
                  "type": "frame",
                  "id": "row-layer-2",
                  "width": "fill-container",
                  "height": "fit-content",
                  "layout": "horizontal",
                  "gap": 24,
                  "padding": 0,
                  "alignItems": "center",
                  "children": [
                    {
                      "type": "text",
                      "id": "label-2",
                      "width": 80,
                      "height": "fit-content",
                      "text": "[层标签]",
                      "fontSize": 20,
                      "textAlign": "right"
                    },
                    {
                      "type": "frame",
                      "id": "layer-2",
                      "width": "fill-container",
                      "height": "fit-content",
                      "borderWidth": 2,
                      "borderRadius": 8,
                      "layout": "vertical",
                      "gap": 16,
                      "padding": 24,
                      "alignItems": "stretch",
                      "children": [
                        {
                          "type": "frame",
                          "id": "subareas-wrapper",
                          "width": "fill-container",
                          "height": "fit-content",
                          "layout": "horizontal",
                          "alignItems": "stretch",
                          "gap": 16,
                          "padding": 0,
                          "children": [
                            {
                              "type": "frame",
                              "id": "subarea-a",
                              "width": "fill-container",
                              "height": "fit-content",
                              "layout": "vertical",
                              "gap": 8,
                              "padding": 12,
                              "borderRadius": 8,
                              "borderWidth": 2,
                              "children": [
                                { "type": "text", "id": "title-a", "width": "fill-container", "height": "fit-content", "text": "[子区域名]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                                {
                                  "type": "frame",
                                  "id": "row-a-1",
                                  "width": "fill-container",
                                  "height": "fit-content",
                                  "layout": "horizontal",
                                  "gap": 8,
                                  "padding": 0,
                                  "children": [
                                    { "type": "rect", "id": "sa-1", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                                    { "type": "rect", "id": "sa-2", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" }
                                  ]
                                }
                              ]
                            },
                            {
                              "type": "frame",
                              "id": "subarea-b",
                              "width": "fill-container",
                              "height": "fit-content",
                              "layout": "vertical",
                              "gap": 8,
                              "padding": 12,
                              "borderRadius": 8,
                              "borderWidth": 2,
                              "children": [
                                { "type": "text", "id": "title-b", "width": "fill-container", "height": "fit-content", "text": "[子区域名]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                                {
                                  "type": "frame",
                                  "id": "row-b-1",
                                  "width": "fill-container",
                                  "height": "fit-content",
                                  "layout": "horizontal",
                                  "gap": 8,
                                  "padding": 0,
                                  "children": [
                                    { "type": "rect", "id": "sb-1", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                                    { "type": "rect", "id": "sb-2", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" }
                                  ]
                                }
                              ]
                            }
                          ]
                        }
                      ]
                    }
                  ]
                },
                {
                  "type": "frame",
                  "id": "row-layer-3",
                  "width": "fill-container",
                  "height": "fit-content",
                  "layout": "horizontal",
                  "gap": 24,
                  "padding": 0,
                  "alignItems": "center",
                  "children": [
                    {
                      "type": "text",
                      "id": "label-3",
                      "width": 80,
                      "height": "fit-content",
                      "text": "[层标签]",
                      "fontSize": 20,
                      "textAlign": "right"
                    },
                    {
                      "type": "frame",
                      "id": "layer-3",
                      "width": "fill-container",
                      "height": "fit-content",
                      "borderWidth": 2,
                      "borderRadius": 8,
                      "layout": "horizontal",
                      "gap": 0,
                      "padding": 24,
                      "justifyContent": "space-around",
                      "children": [
                        { "type": "cylinder", "id": "db-1", "width": 140, "height": "fit-content", "text": "[存储名]", "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                        { "type": "cylinder", "id": "db-2", "width": 140, "height": "fit-content", "text": "[存储名]", "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" }
                      ]
                    }
                  ]
                }
              ]
            },
            {
              "type": "frame",
              "id": "right-sidebar-wrapper",
              "width": 180,
              "height": "fill-container",
              "layout": "vertical",
              "alignItems": "stretch",
              "justifyContent": "space-between",
              "gap": 16,
              "padding": 0,
              "children": [
                {
                  "type": "frame",
                  "id": "side-block-1",
                  "width": "fill-container",
                  "height": "fill-container",
                  "layout": "vertical",
                  "alignItems": "stretch",
                  "justifyContent": "center",
                  "gap": 12,
                  "padding": 16,
                  "borderRadius": 8,
                  "borderWidth": 2,
                  "children": [
                    { "type": "text", "id": "side-title-1", "width": "fill-container", "height": "fit-content", "text": "[侧边栏模块名]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                    {
                      "type": "frame",
                      "id": "side-items-1",
                      "width": "fill-container",
                      "height": "fit-content",
                      "layout": "vertical",
                      "gap": 8,
                      "padding": 0,
                      "children": [
                        { "type": "rect", "id": "s-1", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                        { "type": "rect", "id": "s-2", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" }
                      ]
                    }
                  ]
                },
                {
                  "type": "frame",
                  "id": "side-block-2",
                  "width": "fill-container",
                  "height": "fill-container",
                  "layout": "vertical",
                  "alignItems": "stretch",
                  "justifyContent": "center",
                  "gap": 12,
                  "padding": 16,
                  "borderRadius": 8,
                  "borderWidth": 2,
                  "children": [
                    { "type": "text", "id": "side-title-2", "width": "fill-container", "height": "fit-content", "text": "[侧边栏模块名]", "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                    {
                      "type": "frame",
                      "id": "side-items-2",
                      "width": "fill-container",
                      "height": "fit-content",
                      "layout": "vertical",
                      "gap": 8,
                      "padding": 0,
                      "children": [
                        { "type": "rect", "id": "s-3", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
                        { "type": "rect", "id": "s-4", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" }
                      ]
                    }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

### 岛屿式（网状互联）

```json
{
  "version": 2,
  "nodes": [
    {
      "type": "frame",
      "id": "root",
      "x": 0, "y": 0,
      "width": 1200,
      "height": 800,
      "layout": "none",
      "padding": 24,
      "children": [
        {
          "type": "text",
          "id": "title",
          "x": 0, "y": 0,
          "width": 1152,
          "height": "fit-content",
          "text": "[图表标题]",
          "fontSize": 24,
          "textAlign": "center",
          "verticalAlign": "middle"
        },
        {
          "type": "frame",
          "id": "island-a",
          "x": 40, "y": 60,
          "width": 320,
          "height": "fit-content",
          "layout": "vertical",
          "gap": 12,
          "padding": 20,
          "borderWidth": 2,
          "borderRadius": 8,
          "children": [
            { "type": "text", "id": "island-a-title", "width": "fill-container", "height": "fit-content", "text": "[模块名]", "fontSize": 16, "textAlign": "center", "verticalAlign": "middle" },
            { "type": "rect", "id": "ia-1", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
            { "type": "rect", "id": "ia-2", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" }
          ]
        },
        {
          "type": "frame",
          "id": "island-b",
          "x": 440, "y": 60,
          "width": 320,
          "height": "fit-content",
          "layout": "vertical",
          "gap": 12,
          "padding": 20,
          "borderWidth": 2,
          "borderRadius": 8,
          "children": [
            { "type": "text", "id": "island-b-title", "width": "fill-container", "height": "fit-content", "text": "[模块名]", "fontSize": 16, "textAlign": "center", "verticalAlign": "middle" },
            { "type": "rect", "id": "ib-1", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" },
            { "type": "rect", "id": "ib-2", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" }
          ]
        },
        {
          "type": "frame",
          "id": "island-c",
          "x": 240, "y": 340,
          "width": 320,
          "height": "fit-content",
          "layout": "vertical",
          "gap": 12,
          "padding": 20,
          "borderWidth": 2,
          "borderRadius": 8,
          "children": [
            { "type": "text", "id": "island-c-title", "width": "fill-container", "height": "fit-content", "text": "[模块名]", "fontSize": 16, "textAlign": "center", "verticalAlign": "middle" },
            { "type": "rect", "id": "ic-1", "width": "fill-container", "height": "fit-content", "text": "[节点名]", "borderRadius": 8, "borderWidth": 2, "fontSize": 14, "textAlign": "center", "verticalAlign": "middle" }
          ]
        }
      ]
    },
    { "type": "connector", "connector": { "from": "ia-1", "to": "ib-1", "fromAnchor": "right", "toAnchor": "left", "lineShape": "straight", "lineWidth": 2, "endArrow": "arrow" } },
    { "type": "connector", "connector": { "from": "island-a", "to": "ic-1", "fromAnchor": "bottom", "toAnchor": "top", "lineShape": "rightAngle", "lineWidth": 2, "endArrow": "arrow" } },
    { "type": "connector", "connector": { "from": "island-b", "to": "ic-1", "fromAnchor": "bottom", "toAnchor": "top", "lineShape": "rightAngle", "lineWidth": 2, "endArrow": "arrow" } }
  ]
}
```

## 陷阱

- **所有架构图都用分层条带**：多模块平级网状互联时应选岛屿式；无明确层级时应选网格矩阵。先判断信息结构再选布局。
- **连线过多导致交叉**：架构图非必要不画连线。分层结构本身已表达调用方向，不需要每对节点连线。如果一定要画，最多 3-5 条关键路径。
- **层标签用 frame title（不可读）**：层标签必须用独立的 text 节点放在 frame 外侧（Label-Outside 模式），不要嵌入 frame 内部。
- **cylinder 用 fill-container 宽度**：cylinder 弧度固定 16px 不随宽度缩放，必须用固定宽度（120-200）。
- **侧边栏逻辑混合**："运维监控"和"基础设施"必须是独立 frame，不可合并成一个长条。
- **根节点没有固定宽度**：根 frame 必须有明确宽度（如 1200），否则子节点的 `fill-container` 无法计算。
