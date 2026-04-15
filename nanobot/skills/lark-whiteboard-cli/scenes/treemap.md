# 矩形树图 (Treemap)

## Content 约束

- 分类 3-5 个，每个分类下子项 2-4 个
- 总面积比例需预先计算：每个矩形面积 = 父矩形面积 * (本项数值 / 同级总数值)
- 每个叶子节点标签必须包含数值（如 "{{LABEL}} ({{VALUE}})"）

## Layout 选型

- **脚本生成坐标**（推荐）：Treemap 需要精确的面积比例计算，用 .js 脚本递归切分矩形，脚本输出 JSON 文件后调用 `npx -y @larksuite/whiteboard-cli@^0.2.0` 渲染
- 不适合手动心算坐标

## Layout 规则

- 使用交替切分法（Slice-and-Dice）：奇数层水平切分 width，偶数层垂直切分 height
- 父矩形内必须为标题预留 30-40px 顶部空间，子矩形从 y + 35 开始放置
- 子节点必须完全落在父矩形范围内
- 水平切分时：子 width = 父 width * (子数值 / 父总数值)，子 x 依次累加
- 垂直切分时：子 height = (父 height - 35) * (子数值 / 父总数值)，子 y 依次累加（注意扣除父标签预留的 35px）

### 面积比例计算规则

1. **面积与数值严格成正比**：任何层级的节点，其矩形面积 `width * height` 必须与数值成比例
2. **奇数层水平切分**（如第一层分类）：
   - 父矩形的 `height` 和 `y` 坐标传给所有子节点（扣除标签预留空间后）
   - 按子节点数值占父节点的比例切分父矩形的 `width`：`子width = 父width * (子数值 / 父总数值)`
   - 子节点的 `x` 坐标依次向右累加
3. **偶数层垂直切分**（如第二层子项）：
   - 父矩形的 `width` 和 `x` 坐标传给所有子节点
   - 按子节点数值占父节点的比例切分父矩形的 `height`：`子height = 父height * (子数值 / 父总数值)`
   - 子节点的 `y` 坐标依次向下累加
4. **层层递归**：不断交替水平和垂直切分方向，直到所有叶子节点都被分配了精确的坐标和宽高

### 父标签预留空间

每个非叶子节点的矩形，顶部必须预留 30-40px 放置分类标签。子矩形从父矩形的 `y + 35` 开始放置，可用高度为 `父height - 35`。

示例：父矩形 `{ x: 40, y: 40, height: 700 }`，则：
- 父标签放在 `y: 46`（留 6px 上边距）
- 子矩形从 `y: 75` 开始放置（40 + 35）
- 子矩形可用高度为 `700 - 35 = 665`

## 骨架示例

2 层 treemap：3 个分类（硬件 40、软件 35、服务 25），各含 2 个子项。

根矩形 1100x700，第一层水平切分 width，第二层垂直切分 height。

```json
{
  "version": 2,
  "nodes": [
    {
      "type": "rect",
      "id": "root",
      "x": 40, "y": 40,
      "width": 1100, "height": 700,
      "borderWidth": 2, "borderRadius": 6
    },
    {
      "type": "text",
      "x": 48, "y": 46,
      "width": 1084, "height": 24,
      "text": "{{ROOT_TITLE}}",
      "fontSize": 14
    },

    {
      "type": "rect",
      "id": "cat-A",
      "x": 40, "y": 75,
      "width": 440, "height": 665,
      "borderWidth": 2, "borderRadius": 6
    },
    {
      "type": "text",
      "x": 48, "y": 81,
      "width": 424, "height": 24,
      "text": "{{CAT_A}}",
      "fontSize": 14
    },
    {
      "type": "rect",
      "id": "cat-A-item-1",
      "x": 40, "y": 110,
      "width": 440, "height": 380,
      "borderRadius": 4
    },
    {
      "type": "text",
      "x": 48, "y": 116,
      "width": 424, "height": 24,
      "text": "{{ITEM_A1}} (24)",
      "fontSize": 14
    },
    {
      "type": "rect",
      "id": "cat-A-item-2",
      "x": 40, "y": 490,
      "width": 440, "height": 250,
      "borderRadius": 4
    },
    {
      "type": "text",
      "x": 48, "y": 496,
      "width": 424, "height": 24,
      "text": "{{ITEM_A2}} (16)",
      "fontSize": 14
    },

    {
      "type": "rect",
      "id": "cat-B",
      "x": 480, "y": 75,
      "width": 385, "height": 665,
      "borderWidth": 2, "borderRadius": 6
    },
    {
      "type": "text",
      "x": 488, "y": 81,
      "width": 369, "height": 24,
      "text": "{{CAT_B}}",
      "fontSize": 14
    },
    {
      "type": "rect",
      "id": "cat-B-item-1",
      "x": 480, "y": 110,
      "width": 385, "height": 380,
      "borderRadius": 4
    },
    {
      "type": "text",
      "x": 488, "y": 116,
      "width": 369, "height": 24,
      "text": "{{ITEM_B1}} (20)",
      "fontSize": 14
    },
    {
      "type": "rect",
      "id": "cat-B-item-2",
      "x": 480, "y": 490,
      "width": 385, "height": 285,
      "borderRadius": 4
    },
    {
      "type": "text",
      "x": 488, "y": 496,
      "width": 369, "height": 24,
      "text": "{{ITEM_B2}} (15)",
      "fontSize": 14
    },

    {
      "type": "rect",
      "id": "cat-C",
      "x": 865, "y": 75,
      "width": 275, "height": 665,
      "borderWidth": 2, "borderRadius": 6
    },
    {
      "type": "text",
      "x": 873, "y": 81,
      "width": 259, "height": 24,
      "text": "{{CAT_C}}",
      "fontSize": 14
    },
    {
      "type": "rect",
      "id": "cat-C-item-1",
      "x": 865, "y": 110,
      "width": 275, "height": 399,
      "borderRadius": 4
    },
    {
      "type": "text",
      "x": 873, "y": 116,
      "width": 259, "height": 24,
      "text": "{{ITEM_C1}} (15)",
      "fontSize": 14
    },
    {
      "type": "rect",
      "id": "cat-C-item-2",
      "x": 865, "y": 509,
      "width": 275, "height": 231,
      "borderRadius": 4
    },
    {
      "type": "text",
      "x": 873, "y": 515,
      "width": 259, "height": 24,
      "text": "{{ITEM_C2}} (10)",
      "fontSize": 14
    }
  ]
}
```

面积比例验证（第一层水平切分 width）：
- 硬件 40/100 * 1100 = 440，软件 35/100 * 1100 = 385，服务 25/100 * 1100 = 275
- 子矩形从 y=75 开始，可用高度 665

## 陷阱

- **父标签被子矩形遮挡**（最严重）：子矩形必须从 y + 35（相对父矩形顶部）开始放置，为父分类标签留出空间
- **分类标签不可见**：分类标签 text 节点必须在其子矩形 rect 节点之前添加（z-index 靠后的节点在上层）
- **面积比例不正确**：必须用脚本预先计算比例，不要心算
- **缺少配色区分**：不同顶层分类必须用不同背景色（从色板选取），所有子节点继承对应色系
