---
name: daily-report
description: HiperOne早晚报统一生成与管理 Skill。...
---

# Daily Report Skill

HiperOne早晚报统一生成与管理 Skill。

## 功能

- 早报/晚报内容抓取与生成
- V5 格式标准化输出
- 自动创建飞书子文档
- 封面图生成
- 发送确认与发群

## 使用方法

### 生成早报

```python
from skills.daily_report import generate_daily_report

result = generate_daily_report(
    report_type="早报",  # 或 "晚报"
    date="2026-02-08",
    news_data=news_list,  # 抓取的新闻列表
    deep_topic="自举AI"   # 深度文章主题
)

# 返回结果
{
    "md_file": "/path/to/早报_2026-02-08_V5.md",
    "cover_image": "/path/to/cover_20260208.png",
    "feishu_doc": {
        "obj_token": "...",
        "url": "https://feishu.cn/docx/..."
    }
}
```

### 使用子代理调用

```bash
# 生成早报
sessions_spawn label="早报生成-YYYYMMDD" task="""
执行早报生成流程：
1. 抓取过去12-24小时AI新闻
2. 使用 skills/daily_report/generate.py 生成V5格式早报
3. 在 AI日报存档 下创建飞书子文档
4. 生成封面图
5. 发送给用户确认
"""
```

## 格式模板（V5）

见 `templates/v5_format.md`

## 父节点配置

```yaml
wiki_parents:
  ai_daily_archive:  # 早晚报
    node_token: "LmZ6wKwTViA4bSkVSYfcJGFcnRf"
    space_id: "7313882962775556100"
    
  zhuoran_root:      # 其他内容
    node_token: "Nwwiwh6PNiesZqkWNw7cWegjn2c"
    space_id: "7313882962775556100"
```

## 依赖

- `feishu_wiki` - 创建子文档
- `feishu_doc` - 写入内容
- `web_search` / `web_fetch` - 新闻抓取
- 图像生成 API (DALL-E 3 / Gemini)
