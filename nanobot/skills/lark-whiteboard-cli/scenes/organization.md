# 组织架构图

适用于：公司组织架构、模块依赖树、分类层级树等树形层级结构的场景。

## Content 约束

- 层级 ≤ 4
- 每个父节点下 ≤ 5 个子节点
- 叶节点有意义（不要只为凑数添加空节点）
- 长文本用 `\n` 手动换行（如"研发负责人\n(CTO)"）

## Layout 选型

| 模式 | 适用条件 | 特征 |
|------|---------|------|
| **tree（居中展开）** | 有明确从属关系的层级结构 | 根节点居中，子节点横向排列，逐层展开。每个"父+子"用 vertical frame 包裹（子树模块） |
| **grid（矩阵式）** | 多部门平级，每部门内部有细分 | 横向等分各部门，每部门内部 vertical 列表 |

## Layout 规则

以下规则违反会导致连线错乱或排版崩溃：

1. **子树包裹模式（关键）**：每个父节点和它的子节点群用一个 `layout: "vertical"` + `alignItems: "center"` 的 frame 包裹。**不要**把所有父节点放一层、所有子节点放另一层。*违反后果：父节点与子节点群中心偏移，正交连线无法合并，分裂成两条平行线。*
2. **同层节点建议等高**：同层节点统一 `height`（如 60-70），保证连线横向主轴平直。如果文字长度差异大可用 `fit-content`，但要确保同层文字行数接近。*违反后果：同层节点高低不平，rightAngle 连线横向弯折错乱。*
3. **垂直间距 >= 60**：父子间纵向 `gap: 60`。*违反后果：连线引擎没有足够空间折弯与合并，导致连线穿模或提前分叉。*
4. **叶子容器偶数宽度**：包含叶子节点的横向 frame，宽度应手动计算（子节点宽度之和 + gap × (n-1)），如 2 个 120px 节点 + 20px gap = `width: 260`。或用 `fill-container` 自动等分。*违反后果：父节点中心与子节点群中心有像素级偏差。*
5. **同层兄弟间横向 gap: 20-40**
6. 最小字号 14px
7. 连线：所有父子连线必须 `lineShape: "rightAngle"`（总线风格），`fromAnchor: "bottom"`, `toAnchor: "top"`。*违反后果：失去组织架构图专属的总线视觉效果。*
8. 根 frame 宽度要足够（如 1200-1600），避免叶节点被挤压重叠
9. 不同层级在 fontSize、borderWidth、颜色上递进区分（如 Root 深灰 → L1 浅蓝 → L2 浅绿 → L3 浅紫）
10. 长文本用 `\n` 主动换行（如 "基础架构部\n(包含云原生)"），确保节点高度足够容纳

## 骨架示例

### 树形展开（子树包裹模式）

```json
{
  "version": 2,
  "nodes": [
    {
      "type": "frame",
      "width": 1200,
      "height": "fit-content",
      "layout": "vertical",
      "gap": 48,
      "padding": 40,
      "alignItems": "center",
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
          "type": "rect",
          "id": "root-node",
          "width": 240,
          "height": "fit-content",
          "borderWidth": 3,
          "borderRadius": 8,
          "text": "[根节点名]",
          "fontSize": 18,
          "padding": 12
        },
        {
          "type": "frame",
          "width": "fill-container",
          "height": "fit-content",
          "layout": "horizontal",
          "gap": 40,
          "padding": 0,
          "alignItems": "stretch",
          "children": [
            {
              "type": "frame",
              "width": "fill-container",
              "height": "fit-content",
              "layout": "vertical",
              "gap": 48,
              "padding": 0,
              "alignItems": "center",
              "children": [
                {
                  "type": "rect",
                  "id": "child-a",
                  "width": 200,
                  "height": "fit-content",
                  "borderWidth": 2,
                  "borderRadius": 8,
                  "text": "[子节点名]",
                  "fontSize": 16,
                  "padding": 10
                },
                {
                  "type": "frame",
                  "width": "fill-container",
                  "height": "fit-content",
                  "layout": "horizontal",
                  "gap": 40,
                  "padding": 0,
                  "alignItems": "stretch",
                  "children": [
                    { "type": "rect", "id": "leaf-a1", "width": "fill-container", "height": "fit-content", "borderWidth": 1, "borderRadius": 8, "text": "[叶节点名]", "fontSize": 14, "padding": 8 },
                    { "type": "rect", "id": "leaf-a2", "width": "fill-container", "height": "fit-content", "borderWidth": 1, "borderRadius": 8, "text": "[叶节点名]", "fontSize": 14, "padding": 8 }
                  ]
                }
              ]
            },
            {
              "type": "frame",
              "width": "fill-container",
              "height": "fit-content",
              "layout": "vertical",
              "gap": 48,
              "padding": 0,
              "alignItems": "center",
              "children": [
                {
                  "type": "rect",
                  "id": "child-b",
                  "width": 200,
                  "height": "fit-content",
                  "borderWidth": 2,
                  "borderRadius": 8,
                  "text": "[子节点名]",
                  "fontSize": 16,
                  "padding": 10
                },
                {
                  "type": "frame",
                  "width": "fill-container",
                  "height": "fit-content",
                  "layout": "horizontal",
                  "gap": 40,
                  "padding": 0,
                  "alignItems": "stretch",
                  "children": [
                    { "type": "rect", "id": "leaf-b1", "width": "fill-container", "height": "fit-content", "borderWidth": 1, "borderRadius": 8, "text": "[叶节点名]", "fontSize": 14, "padding": 8 },
                    { "type": "rect", "id": "leaf-b2", "width": "fill-container", "height": "fit-content", "borderWidth": 1, "borderRadius": 8, "text": "[叶节点名]", "fontSize": 14, "padding": 8 }
                  ]
                }
              ]
            }
          ]
        }
      ]
    },
    { "type": "connector", "connector": { "from": "root-node", "to": "child-a", "fromAnchor": "bottom", "toAnchor": "top", "lineShape": "rightAngle", "lineWidth": 2 } },
    { "type": "connector", "connector": { "from": "root-node", "to": "child-b", "fromAnchor": "bottom", "toAnchor": "top", "lineShape": "rightAngle", "lineWidth": 2 } },
    { "type": "connector", "connector": { "from": "child-a", "to": "leaf-a1", "fromAnchor": "bottom", "toAnchor": "top", "lineShape": "rightAngle", "lineWidth": 2 } },
    { "type": "connector", "connector": { "from": "child-a", "to": "leaf-a2", "fromAnchor": "bottom", "toAnchor": "top", "lineShape": "rightAngle", "lineWidth": 2 } },
    { "type": "connector", "connector": { "from": "child-b", "to": "leaf-b1", "fromAnchor": "bottom", "toAnchor": "top", "lineShape": "rightAngle", "lineWidth": 2 } },
    { "type": "connector", "connector": { "from": "child-b", "to": "leaf-b2", "fromAnchor": "bottom", "toAnchor": "top", "lineShape": "rightAngle", "lineWidth": 2 } }
  ]
};

fs.writeFileSync('diagram.json', JSON.stringify(doc, null, 2));
```

## 陷阱

- **分离父子层级（致命错误）**：不要把所有同级父节点放一个 horizontal frame、所有子节点放另一个。必须用 `alignItems: "center"` 的 vertical frame 把每个父节点和它的子节点包裹在一起。
- **同层节点高低不平**：同层节点高度应一致（或文字行数接近），否则 rightAngle 连线横向弯折错乱。
- **垂直间距不足**：父子间 gap 必须 >= 60。不够时连线引擎无法折弯合并。也不要用 80，3-4 层会纵向拉伸过度。
- **做成线性链而非树形展开**：每个父节点的子节点必须横向展开，不要做单链。
- **连线混用 straight**：所有父子连线必须 `lineShape: "rightAngle"`，`fromAnchor: "bottom"`，`toAnchor: "top"`。
- **叶节点字号 12px 看不清**：最小字号 14px。
- **所有节点同一大小和样式**：不同层级必须在 fontSize、borderWidth、颜色上有区分（根>子>叶）。
