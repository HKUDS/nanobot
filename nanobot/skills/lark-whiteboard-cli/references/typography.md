# 排版规则

## 字号层级表

| 层级 | 字号 | 用途 | 对齐 |
|------|------|------|------|
| H1 | 24-28 | 图表标题（每图一个） | center |
| H2 | 18-20 | 分区/层标签 | right（侧标签）或 center（顶部标签） |
| H3 | 15-16 | 分组标题、卡片标题 | center 或 left |
| Body | 14 | 正文、节点文字 | center（短标签）或 left（长文本） |
| Caption | 13 | 辅助说明、注解 | left |

规则：
- 同张图不超过 3 个字号层级
- 同级节点 fontSize 必须完全相同
- 相邻层级字号差 >= 4px

---

## 对齐规则

Shape 节点默认 `textAlign: 'center'` + `verticalAlign: 'middle'`（与 CSS 相反）。如需左对齐须显式声明。

| 内容类型 | 对齐方式 |
|---------|---------|
| 短文本（<=15 字） | center |
| 长文本（>15 字） | left |
| 侧标签（层名、分区名） | right |
| 图表标题 | center |
| 多行描述/段落 | left |

---

## 图表标题

用独立 text 节点，不要用 frame 的 `title` 属性。

- Flex 布局：放在最外层 frame 的第一个 child，`width: "fill-container"`
- 绝对定位：width 设为图表整体宽度，`textAlign: "center"`

---

## 标题和描述拆成两个节点

一个卡片内展示名称和描述时，用 frame 包两个 text 节点，不要塞进同一个 shape：

```json
{
  "type": "frame", "layout": "vertical", "gap": 4, "padding": 12,
  "width": "fill-container", "height": "fit-content",
  "borderWidth": 2, "borderRadius": 8,
  "children": [
    { "type": "text", "width": "fill-container", "height": "fit-content",
      "text": "用户服务", "fontSize": 16 },
    { "type": "text", "width": "fill-container", "height": "fit-content",
      "text": "处理注册登录和个人信息管理", "fontSize": 13 }
  ]
}
```

---

## 图标+文字组合

icon + text 纵向排列时：icon 宽高 36-48px，下方文字 fontSize 12-13，外层 frame gap 4-8。icon 比文字大 2-3 倍时视觉比例最佳。

---

## 尺寸规则

含文字节点 `height` 必须用 `'fit-content'`。写死高度会截断文字。

所有节点必须显式声明 `width` 和 `height`。
