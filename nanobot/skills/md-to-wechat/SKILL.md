---
name: md-to-wechat
description: 将Markdown文件转换为微信公众号兼容的HTML格式，支持自定义主题色、标题、作者等元数据
---
# Markdown转微信公众号HTML

将Markdown格式的文章转换为微信公众号编辑器兼容的HTML格式。

## 功能特点

- ✅ **全内联样式**：兼容微信公众号编辑器，无CSS变量、无伪元素
- ✅ **系统字体栈**：自动适配iOS/安卓/Windows系统字体
- ✅ **丰富组件**：支持标题装饰线、引用块、表格、代码块、场景卡片等
- ✅ **自定义主题**：支持自定义主题色（主色调、强调色等）
- ✅ **元数据支持**：支持设置标题、副标题、作者、标签

## 支持的Markdown语法

| Markdown | 公众号样式 |
|----------|-----------|
| `# 标题` | 文章主标题（封面区域） |
| `## 标题` | 章节标题（带金色装饰线） |
| `### 标题` | 小节标题（带左边框） |
| `> 引用` | 引用块（带大引号装饰） |
| `**加粗**` | 黑色加粗文字 |
| `` `代码` `` | 行内代码（珊瑚色） |
| `\`\`\`代码块\`\`\`` | 深色背景代码块 |
| `| 表格 |` | 精美表格（深色表头） |
| `- 列表` | 无序列表 |
| `【场景重现】` | 场景卡片（珊瑚色边框） |
| `【结论】` | 结论黑框（深色背景） |

## 使用方法

### 命令行

```bash
# 基本用法
./skills/md-to-wechat/scripts/md-to-wechat.sh input.md

# 指定输出文件
./skills/md-to-wechat/scripts/md-to-wechat.sh input.md -o output.html

# 完整参数
./skills/md-to-wechat/scripts/md-to-wechat.sh input.md \
  -o output.html \
  -t "文章标题" \
  -s "副标题描述" \
  -a "作者名称" \
  --tags "标签1,标签2,标签3"
```

### Python API

```python
from skills.md_to_wechat.md_to_wechat import MarkdownToWechatConverter

# 创建转换器
converter = MarkdownToWechatConverter(
    title="文章标题",
    subtitle="副标题",
    author="作者",
    tags=["标签1", "标签2"]
)

# 转换Markdown
with open('input.md', 'r', encoding='utf-8') as f:
    markdown_text = f.read()

html = converter.convert(markdown_text)

# 保存
with open('output.html', 'w', encoding='utf-8') as f:
    f.write(html)
```

## 样式组件说明

### 章节标题（##）
自动生成带金色装饰线的章节标题：
```html
<div style="display:flex;align-items:center;gap:12px;">
  <div style="width:6px;height:28px;background:#d4a574;border-radius:3px;"></div>
  <h2>章节标题</h2>
</div>
```

### 引用块（>）
带大引号装饰的引用块，支持作者署名：
```markdown
> 引用内容
> —— 作者名称
```

### 场景卡片（【标签】）
特殊标记生成珊瑚色边框的场景卡片：
```markdown
【场景重现】
这里是场景描述内容...
```

### 结论黑框（【结论】）
深色背景的结论框：
```markdown
【结论】
这里是结论内容...
```

### 表格
标准Markdown表格转换为精美样式表格：
```markdown
| 项目 | 费用 | 频率 |
|------|------|------|
| Token | $0.003 | 持续 |
| 服务器 | $20 | 月付 |
```

### 代码块
深色背景的代码块，支持语法高亮：
```markdown
```json
{
  "key": "value"
}
```
```

## 主题色配置

默认使用金色+珊瑚色主题，可通过代码自定义：

```python
colors = {
    'primary': '#d4a574',      # 金色 - 主色调
    'accent': '#e07a5f',       # 珊瑚色 - 强调色
    'dark': '#2d3436',         # 深色 - 表格头部
    'text': '#1a1a1a',         # 主文字
    'text_secondary': '#666',  # 次要文字
    'bg_light': '#f5f5f5',     # 浅灰背景
    'bg_card': '#f8f9fa',      # 卡片背景
}

converter = MarkdownToWechatConverter(colors=colors)
```

## 兼容性说明

- ✅ 微信公众号编辑器
- ✅ 企业微信
- ✅ 微信内置浏览器
- ✅ 支持iOS/Android/Windows

## 注意事项

1. **图片处理**：微信编辑器不支持外部图片URL，需上传到微信素材库
2. **预览测试**：务必在iOS和Android真机预览
3. **字数限制**：微信公众号单篇文章建议不超过2万字

## 更新日志

- **v1.0.0** (2026-02-14)
  - 初始版本
  - 支持基础Markdown语法转换
  - 支持场景卡片、结论框等特殊组件
  - 支持自定义主题色
