---
name: feishu-doc-verifier
description: 文档验证子技能 - 使用 Playwright 验证飞书文档是否创建成功。
---

# 文档验证子技能

## 职责
使用 Playwright 访问飞书文档，验证文档是否创建成功并可正常访问。

## 输入
- `doc_info.json` - 由 feishu-doc-creator-v2 生成

## 输出
- `output/verify_result.json` - 验证结果

## 工作流程

### 第一步：加载文档信息
从 `doc_info.json` 加载文档 ID 和 URL。

### 第二步：启动 Playwright
使用持久化上下文启动浏览器。

### 第三步：访问文档
导航到文档 URL，等待页面加载。

### 第四步：验证结果
检查页面标题和内容，确认文档可访问。

### 第五步：保存结果
保存验证结果到 `output/verify_result.json`。

## 数据格式

### verify_result.json 格式
```json
{
  "success": true,
  "document_id": "U2wNd2rMkot6fzxr67ScN7hJn7c",
  "document_url": "https://feishu.cn/docx/U2wNd2rMkot6fzxr67ScN7hJn7c",
  "page_loaded": true,
  "page_title": "文档标题",
  "screenshot": "output/screenshot.png",
  "verified_at": "2026-01-22T10:40:00"
}
```

## 使用方式

### 命令行
```bash
python scripts/doc_verifier.py workflow/step2_create/doc_info.json output
```

### 作为子技能被调用
```python
result = call_skill("feishu-doc-verifier", {
    "doc_info_file": "workflow/step2_create/doc_info.json",
    "output_dir": "workflow/step5_verify"
})
```

## 与其他技能的协作
- 接收来自 `feishu-permission-manager-v2` 的文档信息
- 输出给 `feishu-logger`
