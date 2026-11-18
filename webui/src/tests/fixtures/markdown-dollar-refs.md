我先把你的第二个问题答清楚，因为它决定了第一个问题怎么答。

**nanobot 不用 JSON Schema 的规范实现。** 没有 `jsonschema` 依赖，`base.py` 里 `validate_json_schema_value` 是手写的子集校验器——只认 `type`/`required`/`properties`/`additionalProperties`/`enum`/`min`/`max`/`items` 这些。所以"不认 `$ref`/`anyOf`"不是违反 MCP 规范，是自建校验器不完整。MCP 规范本身也没要求客户端本地校验，责任在 server 一侧。

另外有个作者和我之前都没提的事：`mcp.py` 里**已经有一份完整的 $ref 解析器** `_resolve_local_schema_ref`，支持 JSON Pointer 全路径、`~0`/`~1` 转义、嵌套。它在构造 wrapper 时就把 server 给的本地 ref 全部提升到根 `$defs`。PR 又在 `base.py` 写了一个简化版（只认单段 `#/$defs/x`、`#/definitions/x`，不处理转义和嵌套路径）。对 MCP 工具能用，是因为规整层已经兜住了；但同一件事现在有两套实现。

**具体误拒的例子（我实测了，不是推测）：**

`def book(addr: Address | None = None)` 这种签名，FastMCP 输出 `anyOf: [{$ref: Address}, {type: null}]`，nanobot 的 `_normalize_nullable_schema` 把它折叠成 `{$ref: "#/$defs/Address", nullable: true}`。

然后传 `{"addr": null}` 的结果：

- main：`[]`，通过。
- PR：`["addr should be object"]`，被拦。

原因是新代码先按 `$ref` 解析出的 Address 去校验 `None`，报错了；兄弟关键字 `nullable: true` 虽然判定通过，但只是 `extend`，前面那条错误留在结果里。嵌套可选字段一样中招：`{"user": {"address": null}}` → `["user.address should be object"]`。

模型显式吐 `null` 的情况不算高频，但确实会发生，而且这是**从能用到不能用**的变化，测试里一条都没覆盖（作者的 ref 测试全是必填）。

顺带一个小例子：`oneOf: [{type: integer}, {type: number}]` 传 `3`，被判 `"should match exactly one of the allowed schemas"`——3 同时匹配两支。这是 schema 作者自己写得不严谨，Pydantic 一般发 `anyOf`，所以低频，但 `oneOf` 的严格判定会放大这类问题。

**修法很简单**：`$ref` 分支前先走原有的 nullable 判断——`schema.get("nullable")` 为真且 `val is None` 时直接放行，不要去校验被引用的子 schema。

用一个词总结这个 PR：方向对，实现漏了 nullable，外加重复了一份已经有更好版本的解析器。
