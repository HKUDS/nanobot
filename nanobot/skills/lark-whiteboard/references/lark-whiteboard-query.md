# whiteboard +query（查询画板）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

查询画板内容，支持导出为预览图片、提取 PlantUML/Mermaid 代码，或获取飞书 OpenAPI 原生画板节点格式。

## 参数

| 参数                   | 必填 | 说明                                                                     |
|----------------------|----|------------------------------------------------------------------------|
| `--whiteboard-token` | 是  | 画板 token，需要拥有画板的读权限                                                    |
| `--output_as`        | 是  | 输出格式：`image`（预览图片）、`code`（PlantUML/Mermaid 代码）、`raw`（OpenAPI 原生画板节点格式） |
| `--output`           | 否  | 输出路径。当 `--output_as image` 时必填；当 `--output_as code/raw` 时可选，不填则直接输出到终端 |
| `--overwrite`        | 否  | 覆盖已存在的文件，默认为 false                                                     |

## 输出格式

- `image`：预览图片
- `code`：PlantUML/Mermaid 代码。仅限画板内有且仅有一个 PlantUML/Mermaid 图时，才可导出代码，否则会在返回值中告知不存在/有多个节点。
- `raw`：飞书 OpenAPI 原生画板节点格式。这一 json 格式不适合直接编辑复杂布局或内容，建议仅限于需要修改简单的文本内容/颜色等细节时使用。需要进行更复杂的设计/修改时，建议参考 [lark-whiteboard-cli](../lark-whiteboard-cli/SKILL.md) 。

## 示例

### 示例 1：导出画板为预览图片

```bash
lark-cli whiteboard +query \
  --whiteboard-token "wbcnxxxxxxxx" \
  --output_as image \
  --output ./preview.png
```

### 示例 2：提取画板中的代码并直接输出

```bash
lark-cli whiteboard +query \
  --whiteboard-token "wbcnxxxxxxxx" \
  --output_as code
```

### 示例 3：导出画板原始节点结构到文件

```bash
lark-cli whiteboard +query \
  --whiteboard-token "wbcnxxxxxxxx" \
  --output_as raw \
  --output ./nodes.json \
  --overwrite
```
