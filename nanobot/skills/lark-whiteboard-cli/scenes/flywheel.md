# 增长飞轮图 (Flywheel)

> **必须写脚本生成 JSON。** 飞轮图需要极坐标计算阶段标签位置和 SVG 圆环切割，直接手写 JSON 无法正确实现同心圆环结构。请用下方脚本模板。

## Content 约束

- 阶段 4-6 个，每阶段短标签（title + 可选 subtitle/desc）
- 中心放置飞轮主题标题

## Layout 选型

- **脚本生成坐标**（必须）：用 .js 脚本极坐标计算阶段标签位置、SVG 圆环切割，脚本输出 JSON 文件后调用 `npx -y @larksuite/whiteboard-cli@^0.2.0` 渲染

## Layout 规则

- 同心圆遮挡法构建圆环：大圆（底色）+ 小圆（白色遮罩）+ 中心文字
- nodes 数组顺序决定 z-index：先大圆 -> 小圆 -> 中心文字 -> SVG 切割 -> 外围卡片
- 阶段标签均匀分布在圆环外围，每个标签到圆心距离相等
- SVG polyline 切割圆环形成分段 + 箭头方向感
- 阶段数多时需动态放大半径、缩小箭头折角、收紧文字容器

### 同心圆遮挡法详解

画一个大圆（作为飞轮的底层颜色），然后在它正中心画一个小圆（填充为白色 `#FFFFFF`）。大圆和小圆都设置 `borderWidth: 0`，通过叠加遮挡形成圆环。

nodes 数组中的图层顺序（必须严格遵守）：

1. **底层大圆** (`type: 'ellipse'`, 填色, `borderWidth: 0`)
2. **遮罩小圆** (`type: 'ellipse'`, 白色填色, `borderWidth: 0`)
3. **中心文字** — 必须在两个圆之后添加，否则被白色小圆盖住
4. **SVG 切割箭头** — 覆盖在圆环上，用白色粗线 polyline 切出分段
5. **外围阶段卡片** — 极坐标计算位置

### SVG 箭头线切割分段

通过插入一个铺满大圆区域的 `svg` 节点，利用极坐标计算每个分段交界处的坐标，使用 `<polyline>` 画与背景色相同的粗线条（白色、20px+ 宽度）。线条从内圆边缘穿过大圆边缘，并在穿过时产生一定角度的偏转（`da` 参数），在视觉上"切断"圆环并形成箭头方向感。

### 外围文字环绕布局

- 利用极坐标 `x = cx + R * cos(θ)` 计算每个分段的中心角度
- 在计算出的坐标点放置 `frame` 容器（`layout: 'vertical'`）
- 外围文字容器内部的 `text` 节点不能用 `width: 'fill-container'`，必须指定固定 width 配合 `height: 'fit-content'`

### 动态缩放优化（阶段数 >= 8 时必须）

当阶段数量较多（8 个、12 个或 16 个以上）时，必须动态调整：

- **放大画布与圆环半径**：节点越多，需要越长的圆周容纳外围文字。适当调大 `rOut` 和 `rIn`（如 16 阶段时 `rOut` 可设为 400+），同步放大 `cx`/`cy` 避免超出边界
- **缩小箭头切割角度**：段数增多时每段夹角变小，保持默认折角会导致缝隙过大。应减小 `da`（如 `da = 4`）
- **收紧外围文字容器**：缩窄 `boxWidth`，减小文字字号，确保相邻文本框不互相覆盖

## 骨架示例

此场景必须用 .js 脚本生成。Agent 使用时只需修改 `stages` 数组和 `centerTitle`/`centerSubtitle`，其余坐标全自动计算。

```javascript
const { writeFileSync } = require('fs');

// ══════════════════════════════════════════════════════════════
// 只需修改这里 -- 填入用户要求的阶段数据和中心标题
// ══════════════════════════════════════════════════════════════

const centerTitle = '{{CENTER_TITLE}}';
const centerSubtitle = '{{CENTER_SUBTITLE}}'; // 可选，不需要就留空字符串

const stages = [
  { title: '{{STAGE_1}}', subtitle: '{{SUB_1}}', desc: '{{DESC_1}}' },
  { title: '{{STAGE_2}}', subtitle: '{{SUB_2}}', desc: '{{DESC_2}}' },
  { title: '{{STAGE_3}}', subtitle: '{{SUB_3}}', desc: '{{DESC_3}}' },
  { title: '{{STAGE_4}}', subtitle: '{{SUB_4}}', desc: '{{DESC_4}}' },
];

// ══════════════════════════════════════════════════════════════
// 以下是自动计算逻辑，不需要修改
// ══════════════════════════════════════════════════════════════

// --- 布局参数 ---
const numSegments = stages.length;
const cx = 600, cy = 450; // 画布中心
const rOut = 240, rIn = 160; // 内外圆半径
const textDist = rOut + 40; // 文字离圆心距离
const boxWidth = 220; // 外围文字卡片宽度
const boxHeight = 80; // 估算高度（用于偏移计算）
const da = 8; // 箭头折角

const nodes = [];

// --- 图层 1：底层大圆（圆环底色） ---
nodes.push({
  type: 'ellipse',
  x: cx - rOut, y: cy - rOut,
  width: rOut * 2, height: rOut * 2,
  borderWidth: 0,
});

// --- 图层 2：遮罩小圆（白色） ---
nodes.push({
  type: 'ellipse',
  x: cx - rIn, y: cy - rIn,
  width: rIn * 2, height: rIn * 2,
  borderWidth: 0,
});

// --- 图层 3：中心文字（必须在两个圆之后） ---
nodes.push({
  type: 'text',
  x: cx - rIn, y: cy - (centerSubtitle ? 30 : 20),
  width: rIn * 2, height: 'fit-content',
  text: [{ content: centerTitle, bold: true, fontSize: 32 }],
  textAlign: 'center',
});
if (centerSubtitle) {
  nodes.push({
    type: 'text',
    x: cx - rIn, y: cy + 20,
    width: rIn * 2, height: 'fit-content',
    text: [{ content: centerSubtitle, fontSize: 18 }],
    textAlign: 'center',
  });
}

// --- 图层 4：SVG 切割箭头 ---
let svg = `<svg viewBox="0 0 ${rOut * 2} ${rOut * 2}" xmlns="http://www.w3.org/2000/svg">`;
for (let i = 0; i < numSegments; i++) {
  const a = -90 + i * (360 / numSegments);
  const rad = (a * Math.PI) / 180;
  const radMid = ((a + da) * Math.PI) / 180;
  const R1 = rIn - 5, R2 = rOut + 5, Rm = (rIn + rOut) / 2;
  const x1 = rOut + R1 * Math.cos(rad), y1 = rOut + R1 * Math.sin(rad);
  const x2 = rOut + Rm * Math.cos(radMid), y2 = rOut + Rm * Math.sin(radMid);
  const x3 = rOut + R2 * Math.cos(rad), y3 = rOut + R2 * Math.sin(rad);
  svg += `<polyline points="${x1},${y1} ${x2},${y2} ${x3},${y3}" stroke="#FFFFFF" stroke-width="20" fill="none" stroke-linejoin="round" stroke-linecap="round" />`;
}
svg += `</svg>`;
nodes.push({
  type: 'svg',
  x: cx - rOut, y: cy - rOut,
  width: rOut * 2, height: rOut * 2,
  svg: { code: svg },
});

// --- 图层 5：外围阶段卡片（极坐标计算位置） ---
for (let i = 0; i < numSegments; i++) {
  const stage = stages[i];
  const a = -90 + (360 / numSegments) / 2 + i * (360 / numSegments);
  const rad = (a * Math.PI) / 180;
  const tx = cx + textDist * Math.cos(rad);
  const ty = cy + textDist * Math.sin(rad);

  // 动态偏移：根据角度将文本框向外推
  let offsetX = 0, offsetY = 0;
  if (Math.cos(rad) > 0.1) offsetX = 0;
  else if (Math.cos(rad) < -0.1) offsetX = -boxWidth;
  else offsetX = -boxWidth / 2;
  if (Math.sin(rad) > 0.1) offsetY = 0;
  else if (Math.sin(rad) < -0.1) offsetY = -boxHeight;
  else offsetY = -boxHeight / 2;

  const textW = boxWidth - 24; // 卡片 padding 12 * 2
  nodes.push({
    type: 'frame',
    x: tx + offsetX, y: ty + offsetY,
    width: boxWidth, height: 'fit-content',
    layout: 'vertical', gap: 8, padding: 12,
    alignItems: 'start',
    borderWidth: 2, borderRadius: 8,
    children: [
      { type: 'text', width: textW, height: 'fit-content',
        text: [{ content: stage.title, bold: true, fontSize: 18 }], textAlign: 'left' },
      { type: 'text', width: textW, height: 'fit-content',
        text: [{ content: stage.subtitle, fontSize: 14 }], textAlign: 'left' },
      { type: 'text', width: textW, height: 'fit-content',
        text: [{ content: stage.desc, fontSize: 12 }], textAlign: 'left' },
    ],
  });
}

// --- 图表标题 ---
nodes.push({
  type: 'text',
  x: cx - rOut - 100, y: 30,
  width: (rOut + 100) * 2, height: 'fit-content',
  text: [{ content: centerTitle, bold: true, fontSize: 24 }],
  textAlign: 'center',
});

writeFileSync('diagram.json', JSON.stringify({ version: 2, nodes }, null, 2));
```

## 陷阱

- **中心文字被 SVG 遮挡**：中心文字节点必须在大圆和小圆之后、SVG 之前添加，确保 z-index 正确
- **缺方向指示箭头**：SVG polyline 切割线必须带角度偏转（da 参数），形成顺时针/逆时针箭头感
- **标签位置不对称**：外围卡片必须用极坐标公式 `x = cx + R * cos(θ)` 均匀分布，不可手动摆放
- **外围文字容器死锁**：`layout: 'vertical'` 的 frame 内部 text 节点不能用 `width: 'fill-container'`，必须指定固定 width
