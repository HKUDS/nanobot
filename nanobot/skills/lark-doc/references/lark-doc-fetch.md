
# docs +fetch（获取飞书云文档）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

## 命令

```bash
# 获取文档内容（默认输出 Markdown 文本）
lark-cli docs +fetch --doc "https://xxx.feishu.cn/docx/Z1FjxxxxxxxxxxxxxxxxxxxtnAc"

# 直接传 token
lark-cli docs +fetch --doc Z1FjxxxxxxxxxxxxxxxxxxxtnAc

# 知识库 URL 也支持
lark-cli docs +fetch --doc "https://xxx.feishu.cn/wiki/Z1FjxxxxxxxxxxxxxxxxxxxtnAc"

# 分页获取（大文档）
lark-cli docs +fetch --doc Z1FjxxxxxxxxxxxxxxxxxxxtnAc --offset 0 --limit 50

# 人类可读格式输出
lark-cli docs +fetch --doc Z1FjxxxxxxxxxxxxxxxxxxxtnAc --format pretty
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--doc` | 是 | 文档 URL 或 token（支持 `/docx/` 和 `/wiki/` 链接，系统自动提取 token） |
| `--offset` | 否 | 分页偏移 |
| `--limit` | 否 | 分页大小 |
| `--format` | 否 | 输出格式：json（默认，含 title、markdown、has_more 等字段） \| pretty |

## 重要：图片、文件、画板的处理

**文档中的图片、文件、画板需要通过独立的 media shortcut 单独获取。**

### 识别格式

返回的 Markdown 中，媒体文件以 HTML 标签形式出现：

- **图片**：
  ```html
  <image token="Z1FjxxxxxxxxxxxxxxxxxxxtnAc" width="1833" height="2491" align="center"/>
  ```

- **文件**：
  ```html
  <view type="1">
    <file token="Z1FjxxxxxxxxxxxxxxxxxxxtnAc" name="skills.zip"/>
  </view>
  ```

- **画板**：
  ```html
  <whiteboard token="Z1FjxxxxxxxxxxxxxxxxxxxtnAc"/>
  ```
- 画板编辑：详见 [SKILL.md](../SKILL.md#重要说明画板编辑)

### 获取步骤

1. 从 HTML 标签中提取 `token` 属性值
2. 如果目标是图片/文件素材，且用户只是想查看/预览，调用 [`lark-doc-media-preview`](lark-doc-media-preview.md)（`docs +media-preview`）：
   ```bash
   lark-cli docs +media-preview --token "提取的token" --output ./preview_media
   ```
3. 如果用户明确要下载，或目标是 `<whiteboard token="..."/>`，调用 [`lark-doc-media-download`](lark-doc-media-download.md)（`docs +media-download`）：
   ```bash
   lark-cli docs +media-download --token "提取的token" --output ./downloaded_media
   ```

## Wiki URL 处理策略

知识库链接（`/wiki/TOKEN`）背后可能是云文档、电子表格、多维表格等不同类型的文档。当不确定类型时，**不能直接假设是云文档**，必须先查询实际类型。

### 处理流程

1. **先调用 lark-wiki 解析 wiki token**
2. **从返回的 `node` 中获取 `obj_type`（实际文档类型）和 `obj_token`（实际文档 token）**
3. **根据 `obj_type` 调用对应工具**：

| obj_type | 工具 | 说明 |
|----------|------|------|
| `docx` | `lark-doc-fetch` | 云文档 |
| `sheet` | `lark-sheet` | 电子表格 |
| `bitable` | `lark-base` | 多维表格 |
| 其他 | 告知用户暂不支持 | — |

## 工具组合

| 需求 | 工具 |
|------|------|
| 获取文档文本 | `docs +fetch` |
| 预览图片/文件素材 | `docs +media-preview` |
| 下载图片/文件/画板 | `docs +media-download` |
| 创建新文档 | `docs +create` |
| 更新文档内容 | `docs +update` |

## 参考

- [lark-doc-create](lark-doc-create.md) — 创建文档
- [lark-doc-update](lark-doc-update.md) — 更新文档
- [lark-doc-media-preview](lark-doc-media-preview.md) — 预览素材
- [lark-doc-media-download](lark-doc-media-download.md) — 下载素材/画板缩略图
- [lark-shared](../../lark-shared/SKILL.md) — 认证和全局参数
