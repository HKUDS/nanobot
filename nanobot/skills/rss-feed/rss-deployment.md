# RSS 抓取部署指南

## 环境要求

- Python 3.8+
- feedparser 库
- 网络访问RSS源

## 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/wulaosiji/openclaw.git
cd openclaw/skills/rss-feed

# 2. 安装依赖
pip install feedparser

# 3. 测试运行
python3 rss_fetcher.py
```

## 定时任务配置

### Linux/Mac (crontab)

```bash
# 编辑 crontab
crontab -e

# 添加每小时执行
0 * * * * cd /path/to/openclaw/skills/rss-feed && /usr/bin/python3 rss_fetcher.py >> /var/log/rss-fetch.log 2>>1
```

### OpenClaw Cron

```json
{
  "name": "rss-fetch-hourly",
  "schedule": "0 * * * *",
  "command": "python3 skills/rss-feed/rss_fetcher.py",
  "working_dir": "/path/to/openclaw"
}
```

## 输出目录配置

修改 `rss_fetcher.py` 中的 `DATA_DIR`：

```python
# 默认路径
DATA_DIR = Path("/path/to/your/data/rss-data")
```

## 故障排查

### 超时问题
- 检查网络连接
- 增加 `socket_timeout` 值
- 查看 `max_total_time` 是否足够

### 空数据
- 检查RSS源是否可用（直接用浏览器访问URL）
- 检查是否需要代理
- 查看 `feed.bozo_exception` 错误信息

### 重复数据
- 去重逻辑基于标题完全相同
- 如需模糊去重，需额外实现相似度算法

## 监控建议

1. **数据量监控**：每小时应获取10-50条新闻
2. **成功率监控**：各源成功率应 > 80%
3. **时效性监控**：24小时过滤后不应为空

## 交接清单

- [ ] 代码已同步到共享仓库
- [ ] 依赖已安装
- [ ] 定时任务已配置
- [ ] 输出目录已创建
- [ ] 首次运行测试通过
- [ ] 监控机制已设置
