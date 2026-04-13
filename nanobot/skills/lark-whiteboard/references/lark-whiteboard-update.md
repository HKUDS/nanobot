# whiteboard +update（更新画板）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../../lark-shared/SKILL.md) 了解认证、全局参数和安全规则。

更新画板内容，支持三种输入格式：

- `raw`：飞书 OpenAPI 原生画板节点格式，不推荐直接编辑。
- `plantuml`：PlantUML 代码
- `mermaid`：Mermaid 代码

输入内容可以通过管道从 stdin 读取，或通过 `--source` 指定文件。

## 参数

| 参数                   | 必填 | 说明                                         |
|----------------------|----|--------------------------------------------|
| `--whiteboard-token` | 是  | 画板 token，需要拥有画板的编辑权限                       |
| `--idempotent-token` | 否  | 幂等 token，确保更新操作幂等，最小长度 10 个字符              |
| `--overwrite`        | 否  | 覆盖更新，在更新前删除所有现有内容，默认为 false                |
| `--source`           | 是  | 输入画板内容，支持使用 `@path` 从文件读取，或 `-` 从 stdin 读取 |
| `--input_format`     | 否  | 输入格式：`raw`、`plantuml`、`mermaid`，默认为 `raw`  |

### 以 raw (OpenAPI 原生画板节点格式) 创作

**不要以直接生成 json 语法的方式创作 raw 格式的飞书 OpenAPI 原生画板节点参数**

思维导图，时序图，类图，饼图，流程图等图标推荐使用 Mermaid/PlantUML 语法绘制。

而当需要绘制架构图，组织架构图，泳道图，对比图，鱼骨图，柱状图，折线图，树状图，漏斗图，金字塔图，循环/飞轮图，里程碑或其他较为复杂的图表时，推荐参考 [lark-whiteboard-cli](../lark-whiteboard-cli/SKILL.md)
使用 whiteboard-cli 工具创作。

## 示例

### 示例 1：使用 PlantUML 代码更新画板（从 stdin 读取）

```bash
# 编写 PlantUML 代码
cat > diagram.puml << 'EOF'
@startuml
Alice -> Bob: Hello
Bob -> Alice: Hi
@enduml
EOF

# 通过管道传递给命令
cat diagram.puml | lark-cli whiteboard +update \
  --whiteboard-token <画板Token> \
  --input_format plantuml --source -\
  --overwrite --yes --as user
```

### 示例 2：使用 Mermaid 代码更新画板（从文件读取）

```bash
# 编写 Mermaid 代码
cat > diagram.mmd << 'EOF'
graph TD
    A[开始] --&gt; B{判断}
    B --&gt;|是| C[处理]
    B --&gt;|否| D[结束]
    C --&gt; D
EOF

# 从文件读取并更新
lark-cli whiteboard +update \
  --whiteboard-token <画板Token> \
  --input_format mermaid \
  --source @./diagram.mmd \
  --overwrite --yes --as user
```

### 示例 3：使用 whiteboard-cli 直接使用画板 DSL 更新画板

whiteboard-cli 工具的具体用法请参考 [../lark-whiteboard-cli/SKILL.md](../lark-whiteboard-cli/SKILL.md)

```bash
# 使用 whiteboard-cli 生成 OpenAPI 格式并通过管道传递
npx -y @larksuite/whiteboard-cli@^0.1.0 --to openapi -i <画板 DSL> --format json | lark-cli whiteboard +update \
  --whiteboard-token <画板Token> \
  --input_format raw --source -\
  --overwrite --yes --as user
```

### 示例 4：使用 whiteboard-cli 使用画板 DSL 生成 Raw 格式 Json，并使用其更新画板

whiteboard-cli 工具的具体用法请参考 [../lark-whiteboard-cli/SKILL.md](../lark-whiteboard-cli/SKILL.md)

```bash
# 使用 whiteboard-cli 生成 OpenAPI 格式并通过管道传递
npx -y @larksuite/whiteboard-cli@^0.1.0 --to openapi -i <画板 DSL> -o ./temp.json

lark-cli whiteboard +update \
  --whiteboard-token <画板Token> \
  --input_format raw \
  --source @./temp.json \
  --overwrite --yes --as user
```
