# 鱼骨图（因果图）

> **必须写脚本生成 JSON。** 鱼骨图的分支角度、原因小骨坐标需要三角函数计算，直接手写 JSON 极易导致节点重叠和连线穿模。请用下方脚本模板。

## Content 约束

- 分类 4-6 个
- 每个分类的原因 ≤ 4
- 总原因 ≤ 20（超过必须合并分类）

## Layout 选型

- **脚本生成坐标**（必须）：用 .js 脚本通过三角函数计算鱼骨坐标，脚本输出 JSON 文件后调用 `npx -y @larksuite/whiteboard-cli@^0.2.0` 渲染

## Layout 规则

- 主干水平居中，从左向右延伸
- 分类节点按 spineX 从左到右排列，奇数（第 1、3、5...）在上方，偶数（第 2、4...）在下方
- 每个分类的原因沿斜线（分支骨）等距排列
- 鱼头（中心问题）在右侧，用 ellipse
- 主干连线带箭头指向鱼头，分支骨和原因小骨连线 endArrow: "none"
- 原因小骨水平延伸到原因框右侧，Y 坐标精准对齐

## 骨架示例

**上下交替**：分类标签按 spineX 从左到右排列，奇数（第1、3、5...）在上方，偶数（第2、4...）在下方。

**视觉同色系**：同一个分支的分类标签、连线及其下的所有原因节点，必须使用同一个色系（如相同的背景色与边框色组合），以保持图形风格统一和逻辑连贯。可以预定义一组颜色数组，按分支轮询使用。

### 坐标计算脚本模板（必须严格参照此算法生成）

以下 Node.js 脚本模板包含了完整的动态布局算法，能够自动适配任意数量的分类和原因，生成完美不重叠的鱼骨图：

```javascript
const fs = require('fs');

const nodes = [];

// 1. 数据定义 (根据用户需求填充)
const categories = [
  { id: "c0", text: "前端代码", reasons: ["未压缩资源", "冗余请求", "超大图片未懒加载"] },
  { id: "c1", text: "后端服务", reasons: ["数据库慢查询", "缓存失效", "并发量过大"] },
  { id: "c2", text: "网络环境", reasons: ["CDN配置错误", "DNS解析缓慢", "带宽限制", "网络抖动"] }
];

// 2. 动态布局计算
const catWidth = 120;
const catHeight = 40;
const reasonWidth = 140; // 调整原因框宽度以适应长文本
const reasonHeight = 32;
const lineLength = 20; // 原因小骨连线的水平延伸长度
const paddingX = 40; // 同侧节点间的水平安全间距

// 预置的分支色系数组（分支骨分类和具体原因保持同一色系）
const branchColors = [
  { fill: "#E8F3FF", stroke: "#1664FF" }, // 蓝色系
  { fill: "#E6FFED", stroke: "#00B42A" }, // 绿色系
  { fill: "#FFF7E8", stroke: "#FF7D00" }, // 橙色系
  { fill: "#FFECE8", stroke: "#F5319D" }, // 粉色系
  { fill: "#F2E8FF", stroke: "#722ED1" }, // 紫色系
  { fill: "#E8FFFF", stroke: "#14C9C9" }  // 青色系
];

let maxSpineY_up = 0;
let maxSpineY_down = 0;

// 第一步：计算每个 category 的内部尺寸和相对包围盒
categories.forEach((cat, index) => {
  const isTop = index % 2 === 0;
  const numReasons = cat.reasons.length;

  // 动态计算分支高度，确保原因小骨不会垂直重叠
  // 每个原因需要 reasonHeight + 上下间距(约 16)
  const requiredY = (numReasons + 1) * (reasonHeight + 16);
  const branchDY = Math.max(160, requiredY);
  const branchDX = -branchDY * 0.7; // 保持固定的倾斜角度向左延伸

  cat.isTop = isTop;
  cat.branchDX = branchDX;
  cat.branchDY = branchDY;

  // 记录最大分支高度，用于计算背景高度和主骨 Y 坐标
  if (isTop) maxSpineY_up = Math.max(maxSpineY_up, branchDY + catHeight + 40);
  else maxSpineY_down = Math.max(maxSpineY_down, branchDY + catHeight + 40);

  // 计算该分类的相对包围盒的极值（相对于 spineX 锚点）
  // 最左侧可能由分类框或原因框决定
  cat.minX = Math.min(branchDX - catWidth / 2, branchDX - lineLength - reasonWidth);
  // 最右侧为主骨挂载点 0 或 分类框右侧
  cat.maxX = Math.max(0, branchDX + catWidth / 2);
});

// 第二步：计算每个 category 在主骨上的绝对 X 坐标 (spineX)
let currentSpineX = 100; // 初始偏移
for (let i = 0; i < categories.length; i++) {
  const cat = categories[i];
  let startX = currentSpineX;

  // 需要和上一个同侧的 category 保持距离，防止水平重叠
  if (i >= 2) {
    const prevSameSideCat = categories[i - 2];
    const requiredX = prevSameSideCat.spineX + prevSameSideCat.maxX - cat.minX + paddingX;
    startX = Math.max(startX, requiredX);
  }

  // 确保左侧最长分支不会超出画布左边界
  if (startX + cat.minX < 50) {
    startX = 50 - cat.minX;
  }

  cat.spineX = startX;
  // 每次略微向前推进，确保异侧节点也能稍微错开
  currentSpineX = startX + 80;
}

// 第三步：计算全局画布尺寸
const lastCat = categories[categories.length - 1];
const spineY = maxSpineY_up + 50; // 动态推导主骨 Y 坐标
const totalWidth = lastCat.spineX + 350; // 右侧留出鱼头的空间
const totalHeight = spineY + maxSpineY_down + 50;

// 4. 生成节点数据
// 背景
nodes.push({ type: "rect", x: 0, y: 0, width: totalWidth, height: totalHeight, fillColor: "#FFFFFF", borderWidth: 0 });

// 鱼头
const headWidth = 180;
const headHeight = 80;
const headX = totalWidth - headWidth - 40;
const headY = spineY - headHeight / 2;
nodes.push({ type: "ellipse", id: "head", x: headX, y: headY, width: headWidth, height: headHeight, text: "核心问题" });

// 主骨连线
const firstSpineX = categories[0].spineX + categories[0].minX;
nodes.push({
  type: "connector",
  connector: { from: { x: firstSpineX, y: spineY }, to: "head", toAnchor: "left", lineShape: "straight", endArrow: "arrow" }
});

// 遍历生成分类和原因小骨
categories.forEach((cat, index) => {
  const isTop = cat.isTop;
  const branchDY = cat.branchDY;
  const branchDX = cat.branchDX;
  const color = branchColors[index % branchColors.length];

  // 分类标签
  const catX = cat.spineX + branchDX - catWidth / 2;
  const catY = spineY + (isTop ? -branchDY - catHeight : branchDY);

  nodes.push({
    type: "rect", id: cat.id, x: catX, y: catY, width: catWidth, height: catHeight, text: cat.text,
    fillColor: color.fill, strokeColor: color.stroke
  });
  // 分支骨连线
  nodes.push({
    type: "connector",
    connector: { from: { x: cat.spineX, y: spineY }, to: cat.id, toAnchor: isTop ? "bottom" : "top", lineShape: "straight", endArrow: "none", lineColor: color.stroke }
  });

  // 原因小骨
  cat.reasons.forEach((reason, rIndex) => {
    // 线性插值，均匀分布在分支骨上
    const t = (rIndex + 1) / (cat.reasons.length + 1);
    const attachX = cat.spineX + branchDX * t;
    const attachY = spineY + (isTop ? -branchDY : branchDY) * t;

    // 关键对齐：确保原因盒子完全在连线左侧，并且 Y 坐标中心精准对齐
    const boxX = attachX - lineLength - reasonWidth;
    const boxY = attachY - reasonHeight / 2;

    const rId = `${cat.id}-r${rIndex}`;
    nodes.push({
      type: "rect", id: rId, x: boxX, y: boxY, width: reasonWidth, height: reasonHeight, text: reason,
      fillColor: color.fill, strokeColor: color.stroke
    });
    // 原因小骨连线
    nodes.push({
      type: "connector",
      connector: { from: { x: attachX, y: attachY }, to: rId, toAnchor: "right", lineShape: "straight", endArrow: "none", lineColor: color.stroke }
    });
  });
});

fs.writeFileSync('diagram.json', JSON.stringify({ version: 2, nodes }, null, 2));
```

## 连线格式与注意点

所有 connector 都用 `{ "type": "connector", "connector": { ... } }` 格式。
**注意：除了主骨外，其他所有连线（分支骨、原因小骨）都必须设置 `"endArrow": "none"`，否则会默认带箭头，导致方向混乱。**

分支骨：从主骨上的绝对坐标点 → 分类标签节点：

```json
{
  "version": 2,
  "nodes": [
    { "type": "rect", "x": 0, "y": 0, "width": "__totalWidth__", "height": "__totalHeight__" },

    { "type": "ellipse", "id": "head", "x": "__headX__", "y": "__headY__",
      "width": 180, "height": 80, "text": "[中心问题]" },

    { "type": "connector", "connector": {
      "from": { "x": "__spineStartX__", "y": "__spineY__" },
      "to": "head", "toAnchor": "left",
      "lineShape": "straight", "endArrow": "arrow"
    }},

    { "type": "rect", "id": "c0", "x": "__catX__", "y": "__catY__",
      "width": 120, "height": 40, "text": "[分类A]" },
    { "type": "connector", "connector": {
      "from": { "x": "__spineX0__", "y": "__spineY__" },
      "to": "c0", "toAnchor": "bottom",
      "lineShape": "straight", "endArrow": "none"
    }},

    { "type": "rect", "id": "c0-r0", "x": "__reasonX__", "y": "__reasonY__",
      "width": 140, "height": 32, "text": "[原因1]" },
    { "type": "connector", "connector": {
      "from": { "x": "__attachX__", "y": "__attachY__" },
      "to": "c0-r0", "toAnchor": "right",
      "lineShape": "straight", "endArrow": "none"
    }}
  ]
}
```

上述骨架展示一个分类（上方）+ 一条原因的模式。完整鱼骨图重复此模式，上下交替。每个分类下可有多条原因，均匀插值分布在分支骨上。

## 陷阱

- **代码生成**：必须使用带有动态防重叠算法的脚本来计算坐标并输出 JSON。
- **分支骨防重叠**：同一侧的相邻分支骨和原因框必须没有任何交叉。
- **自适应高度**：原因数量较多时，分支骨自动拉长以容纳所有小骨。
- **原因小骨水平**：原因框右侧的附着点必须与连线起点 Y 坐标一致。
- **无箭头**：所有分类的分支连线、小骨连线均必须关闭箭头。
- **同色系**：同一个分支骨、分类标签节点以及原因小骨节点和连线，必须使用同色系的颜色以保持视觉连贯性。
