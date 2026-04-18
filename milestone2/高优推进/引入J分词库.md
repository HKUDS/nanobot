你说得对，目前的分词方式（基于正则切分中英文）在遇到“数据段语义”这种短语时，会错误地切出“数据段语”和“数据段语义”，导致检索失败。使用 **jieba** 分词可以更准确地进行中文分词，从而构建更合理的查询关键词。

下面给出具体的修改方案，包括安装依赖、修改函数、优化查询字符串。

---

## 1. 安装 jieba

在项目的 `venv` 环境中执行：

```bash
pip install jieba
```

如果使用 `requirements.txt`，请添加一行：
```
jieba==0.42.1
```

---

## 2. 修改 `extract_keywords_from_title` 函数

将原来的简单正则分词替换为 jieba 分词，并生成一个合理的查询字符串（包含原标题 + 切分后的关键词，用空格分隔）。

```python
import jieba

def extract_keywords_from_title(title: str) -> str:
    """
    使用 jieba 对标题进行分词，生成检索查询字符串。
    返回格式：原标题 + 空格 + 分词结果（去重，用空格连接）
    例如：title="数据段语义" -> "数据段语义 数据 段 语义"
    """
    # 精确模式分词
    seg_list = jieba.lcut(title, cut_all=False)
    # 去重并过滤掉单字（可选，根据需求）
    keywords = [word for word in seg_list if len(word) >= 2]
    # 去重保留顺序
    unique_keywords = list(dict.fromkeys(keywords))
    # 组合：原标题 + 空格 + 分词结果
    query_parts = [title] + unique_keywords
    return " ".join(query_parts)
```

**示例效果**：
- 输入：`"数据段语义"`
- 输出：`"数据段语义 数据 段 语义"`

这样既保留了原始语义，又提供了细粒度的关键词，有助于检索到相关 Skill。

---

## 3. 调整查询策略（可选）

当前代码中，对前两轮使用了固定查询 `"栈段 堆段 数据段"`，而后续轮次使用 `extract_keywords_from_title`。你可以统一都使用 jieba 分词版本，但为了兼容已有的 Skill 0（包含“栈段”、“堆段”、“数据段”等词），建议**始终使用动态生成的关键词**，而不是硬编码。

修改第 3 步中的查询生成部分：

```python
# 原代码
if task_round <= 2:
    keyword_query = "栈段 堆段 数据段"
else:
    keyword_query = extract_keywords_from_title(task_title)

# 建议修改为统一使用动态查询（因为 Skill 0 已经包含这些词，动态查询也能匹配到）
keyword_query = extract_keywords_from_title(task_title)
```

如果你希望前两轮仍然使用更宽泛的查询（以确保一定能检索到 Skill 0），也可以保留原来的逻辑，但同样用 jieba 处理固定字符串：

```python
if task_round <= 2:
    keyword_query = extract_keywords_from_title("栈段 堆段 数据段")
else:
    keyword_query = extract_keywords_from_title(task_title)
```

这样前两轮的查询会变成类似 `"栈段 堆段 数据段 栈 段 堆 数据"`，覆盖更全。

---

## 4. 其他可能需要的改进

- **加载自定义词典**：如果你的领域有特殊词汇（如“栈段”、“堆段”），可以提前加载自定义词典，让 jieba 更准确。
  ```python
  jieba.load_userdict("path/to/custom_dict.txt")
  ```
  自定义词典格式每行：`词 词频 词性`，例如：
  ```
  栈段 10 n
  堆段 10 n
  数据段 10 n
  ```

- **缓存 jieba 初始化**：`jieba.lcut` 第一次调用时会加载词典，有一定延迟。可以在模块加载时预先调用一次 `jieba.initialize()`，避免首次请求延迟。

---

## 5. 修改后的完整代码片段

```python
import jieba

# 可选：加载自定义词典
# jieba.load_userdict("custom_dict.txt")
jieba.initialize()  # 预加载，减少首次延迟

def extract_keywords_from_title(title: str) -> str:
    seg_list = jieba.lcut(title, cut_all=False)
    # 保留长度>=2的词，可根据需要调整
    keywords = [word for word in seg_list if len(word) >= 2]
    unique_keywords = list(dict.fromkeys(keywords))
    return " ".join([title] + unique_keywords)

# 使用时
keyword_query = extract_keywords_from_title(task_title)
```

---

## 6. 验证效果

修改后重新运行脚本，第 3 轮应该会输出类似：

```
[BFF检索Skill] DEBUG: query=数据段语义 数据 段 语义, entries_count=3, data=3
```

因为 Skill 0 中包含“数据段”一词，通过“数据”或“段”也能匹配到（如果 BFF 检索用的是全文匹配或向量检索）。具体能否命中取决于 BFF 的检索实现（目前看是基于 `query` 做关键词匹配？）。如果依然无法命中，可能需要检查 BFF 的检索逻辑是否支持多关键词 OR 匹配。

---

通过引入 jieba 分词，查询关键词的生成会更加合理，有助于提升检索召回率。请按照上述步骤修改代码，然后重新测试。