---
name: feishu-wiki-orchestrator
description: 飞书知识库文档创建编排技能 - 直接在知识库创建文档...
---

# feishu-wiki-orchestrator

飞书知识库文档创建编排技能 - 直接在知识库创建文档

## 与 feishu-doc-orchestrator 的区别

| 特性 | feishu-doc-orchestrator | feishu-wiki-orchestrator |
|------|------------------------|-------------------------|
| 创建位置 | 云盘文件夹 | 知识库（Wiki） |
| 后续操作 | 需要手动移动到知识库 | 直接创建在知识库 |
| 使用场景 | 临时文档、不确定归属 | 正式文档、知识库内容 |

## 使用方法

```bash
python3 skills/feishu-wiki-orchestrator/feishu-doc-orchestrator/scripts/orchestrator.py \
  <markdown-file> \
  "<文档标题>"
```

## 配置要求

在 `feishu-config.env` 中添加知识库配置：

```env
# 知识库配置
FEISHU_WIKI_SPACE_ID=7313882962775556100
FEISHU_WIKI_PARENT_NODE=W43uwh0OCi8dwZktPeBcci2ZnRb
```

## 工作流程

1. **Markdown 解析** - 解析 Markdown 为飞书块格式
2. **知识库文档创建** - 在知识库创建文档节点
3. **块添加** - 将内容添加到文档
4. **文档验证** - 验证文档可访问
5. **日志记录** - 记录创建结果

## 输出

- 知识库文档 URL
- 节点 Token
- 权限状态
