# 流程图 (Flowchart)

适用于：各种业务流转图、决策树、审批流、时序控制逻辑、带条件判断的链路、系统架构拓扑等。

通用字段语义详见 `references/schema.md`，通用布局原则详见 `references/layout.md`；本文件只描述流程图场景下的选型边界与范式。

> [!IMPORTANT]
> **流程图必须走 DSL 路径，不再使用 Mermaid！**
> 复杂分支、判断、回路、跳级关系优先使用 `layout: "dagre"` 计算拓扑；如果只是规整的单线流水线，且卡片强对齐比自动拓扑更重要，也可以使用 Flex + 顶层 `connector` 组合实现。

## 美学规范

- **摒弃简陋节点，推崇全卡片化**：核心业务节点不要只用一个纯文本 `rect`。**应优先采用 Flex 组合卡片**（如：在 `vertical` frame 内上下组合【Emoji 标题项】和【补充说明项】），使得节点信息结构化、层级分明。
- **语义化色彩编排**：节点底色严禁随机分配。必须按状态语义映射：常规链路用浅蓝/浅紫、核心风控/检查用预警黄、成功通过用生命绿、失败熔断用危险红。边框颜色可同色系加深，以凸显卡片边缘。
- **统一判定逻辑**：条件分支必须使用 `diamond` 菱形节点，并且**严禁漏掉** `layoutOptions.edges` 边定义里的第三个标签参数（必须清晰写明"是/否"、"通过/拒绝"）。
- **形状多样化**：合理搭配不同形状来表达语义 —— `ellipse` 用于外部实体/起终点、`diamond` 用于判断路由、`rect` 用于业务处理节点、`cylinder` 用于持久化存储。

## Layout 选型

| 模式             | 适用条件                                       | 核心配置                                                                                                 |
| ---------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| **主体用 Dagre** | 有判断、分支、回路、回退、跳级关系的标准流程图 | 主体 frame 设定 `layout: "dagre"`，按需配置 `rankdir: "TB"` 或 `rankdir: "LR"`。                          |
| **局部复合节点** | 流程中的某一步本身是一个小型 UI 组合体         | 外层仍用 `dagre`，复合步骤内部改用 `layout: "vertical"` / `"horizontal"`。此类节点为**不透明节点**，外层连线只能连到外壳。 |
| **透明子图**     | 需按业务区域分组，且连线穿越区域边界           | 子容器声明 `layout: "dagre"` + `layoutOptions: { isCluster: true }`，成为透明子图。内部节点直接参与外层拓扑运算。 |
| **规整流水线**   | 基本是单线 A → B → C → D，且卡片对齐要求极高   | 主体可用 Flex 排版，连线改用顶层 `connector`；不要为了"自动"而硬上 Dagre。                                  |

## 核心属性

- **`rankdir`**: `TB`（上下）或 `LR`（左右）。**强烈推荐优先使用 `LR`**，充分利用宽屏横向空间。
- **`edges`**: 在根 Dagre 的 `layoutOptions.edges` 中按 `[fromId, toId, "标签"]` 声明。**支持反向连接**实现闭环。所有 edges 统一写在**最外层根 Dagre**，不要写在 cluster 内部。
- **`ranksep` 与边文本**: 若边上标注了说明文字，**必须根据字数调大间距**：`ranksep = max(60, 字数 × 16)`。
- **自适应尺寸**: dagre 容器**必须**设定 `width: "fit-content"` 和 `height: "fit-content"`。
- **`clusterTitle`**: 透明子图可通过 `clusterTitle` 声明悬浮标题（自动吸附左上角、加粗 14px），搭配 `clusterTitleColor` 指定标题颜色。

## 两种嵌套模式

### 不透明节点（Opaque Node）
Dagre 内的子容器，只要未声明 `isCluster: true`，对外层 Dagre 就是具有确定宽高的原子节点。外层连线无法寻址其内部子节点。适合封装复杂的组合卡片（如带图标、版本号、多行描述的业务模块）。

### 透明子图（Compound Cluster）
子容器同时声明 `layout: "dagre"` 与 `layoutOptions: { isCluster: true }` 时，成为外层 Dagre 的复合子图。其内部子节点直接参与外层拓扑运算，连线可穿越子图边界。适合划分网络区域、功能层级、命名空间等边界容器。推荐搭配 `borderDash: "dashed"` 虚线边框 + 淡色背景。

## 骨架示例（推荐范本）

以下是一个混合架构拓扑的完整示例。它同时展示了**透明子图**（Kubernetes Zone，连线可穿透）和**不透明复合节点**（DB 集群、AI 引擎，连线只能连外壳）的标准写法，以及多种形状（ellipse / diamond / rect / cylinder）和语义化配色规范。

```json
{
  "version": 2,
  "nodes": [
    {
      "type": "frame",
      "id": "root",
      "x": 20, "y": 20,
      "layout": "dagre",
      "width": "fit-content", "height": "fit-content",
      "padding": 60,
      "fillColor": "#F8FAFC",
      "borderColor": "#CBD5E1",
      "borderWidth": 1,
      "borderRadius": 16,
      "layoutOptions": {
        "rankdir": "LR",
        "nodesep": 60,
        "ranksep": 120,
        "edges": [
          ["user", "k8s_ingress", "HTTPS request"],
          ["k8s_ingress", "web_pod", "Route UI"],
          ["k8s_ingress", "api_pod", "Route API"],
          ["web_pod", "api_pod", "Internal REST"],
          ["api_pod", "db_cluster", "SQL Query"],
          ["api_pod", "ai_service", "gRPC Stream"]
        ]
      },
      "children": [
        {
          "type": "ellipse", "id": "user", "text": "Global Users",
          "width": 110, "height": 60,
          "fillColor": "#E2E8F0", "borderColor": "#64748B", "borderWidth": 1,
          "fontSize": 14, "textColor": "#334155"
        },
        {
          "type": "frame", "id": "zone_k8s",
          "layout": "dagre",
          "layoutOptions": {
            "isCluster": true,
            "clusterTitle": "☸️ Kubernetes Zone (isCluster)",
            "clusterTitleColor": "#2563EB"
          },
          "fillColor": "#EFF6FF", "borderColor": "#60A5FA",
          "borderWidth": 2, "borderDash": "dashed", "borderRadius": 24,
          "children": [
            {
              "type": "diamond", "id": "k8s_ingress", "text": "Nginx Ingress",
              "width": 130, "height": 70,
              "fillColor": "#DBEAFE", "borderColor": "#3B82F6", "borderWidth": 2,
              "textColor": "#1E40AF"
            },
            {
              "type": "rect", "id": "web_pod", "text": "Next.js SSR Pod",
              "width": 140, "height": 48,
              "fillColor": "#BFDBFE", "borderColor": "#2563EB", "borderWidth": 2,
              "borderRadius": 8, "textColor": "#1E3A8A"
            },
            {
              "type": "rect", "id": "api_pod", "text": "Go Lang API Pod",
              "width": 140, "height": 48,
              "fillColor": "#BFDBFE", "borderColor": "#2563EB", "borderWidth": 2,
              "borderRadius": 8, "textColor": "#1E3A8A"
            }
          ]
        },
        {
          "type": "frame", "id": "db_cluster",
          "layout": "vertical", "gap": 16, "padding": [20, 24],
          "alignItems": "center",
          "fillColor": "#F0FDF4", "borderColor": "#22C55E",
          "borderWidth": 2, "borderRadius": 16,
          "children": [
            {
              "type": "text", "id": "db_title",
              "text": "🗄️ Highly Available DB (不透明)", "fontSize": 14, "textColor": "#14532D"
            },
            {
              "type": "frame", "id": "db_row", "layout": "horizontal", "gap": 20,
              "children": [
                {
                  "type": "cylinder", "id": "db_master", "text": "Master",
                  "width": 80, "height": 50,
                  "fillColor": "#DCFCE7", "borderColor": "#16A34A", "borderWidth": 1,
                  "textColor": "#166534"
                },
                {
                  "type": "cylinder", "id": "db_replica", "text": "Replica",
                  "width": 80, "height": 50,
                  "fillColor": "#DCFCE7", "borderColor": "#16A34A", "borderWidth": 1,
                  "textColor": "#166534"
                }
              ]
            }
          ]
        },
        {
          "type": "frame", "id": "ai_service",
          "layout": "vertical", "gap": 10, "padding": [16, 20],
          "alignItems": "center",
          "fillColor": "#FAF5FF", "borderColor": "#A855F7",
          "borderWidth": 2, "borderRadius": 12,
          "children": [
            {
              "type": "text", "id": "ai_title",
              "text": "🧠 Multi-Modal Engine (不透明)", "fontSize": 14, "textColor": "#6B21A8"
            },
            {
              "type": "rect", "id": "ai_version",
              "text": "v4.2.1-beta", "width": 90, "height": 22,
              "fillColor": "#E9D5FF", "borderColor": "#C084FC", "borderWidth": 1,
              "borderRadius": 4, "fontSize": 11, "textColor": "#581C87"
            },
            {
              "type": "text", "id": "ai_desc",
              "text": "Includes Vector Store\n& Transformer Blocks",
              "fontSize": 12, "textColor": "#7E22CE", "textAlign": "center"
            }
          ]
        }
      ]
    }
  ]
}
```

**范本要点**：
- `zone_k8s` 是**透明子图**（`isCluster: true` + `clusterTitle`），外部连线穿越虚线边界直达 `k8s_ingress`、`web_pod`、`api_pod`。
- `db_cluster` 和 `ai_service` 是**不透明节点**（`layout: "vertical"`），内部用 Flex 组合了多行结构化信息，对外层 Dagre 是固定宽高的原子。连线只能连到外壳 ID。
- 所有 `edges` 统一写在最外层根 Dagre 的 `layoutOptions` 中。
- 本范本中用到了 `ellipse`（外部实体）、`diamond`（路由判断）、`rect`（业务节点）、`cylinder`（数据库存储）四种形状。

## 陷阱与常见报错防范

- **误用 Mermaid**：只要用户没有带 `mermaid` 具体语法代码，哪怕描述明确是"流程图"，也**强制使用 DSL 框架下的 Dagre 模式**。
- **重复画线**：`dagre` 里的所有子节点关系通过 `edges` 定义，引擎会自动生成连线。**绝对不要再去外层用 `connector` 节点重复连一次**。
- **穿透黑盒**：普通子容器是不透明节点，外部连线无法直接寻址其内部子节点（引擎会自动重定向至外壳）。若需穿透，必须声明 `layout: "dagre"` 与 `layoutOptions: { isCluster: true }`。
- **`id` 缺失**：只要是在 `edges` 里出现的标识符，`children` 里一定能找到同名 `id` 的节点对应，拼写必须完全一致。
- **宽度灾难**：Dagre 内容器禁止子框使用 `fill-container`，因为 dagre 父容器本身是被内容撑开的。
