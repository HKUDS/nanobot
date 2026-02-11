---
name: douban-movie
description: 查询豆瓣电影榜单、即将上映影片、推荐电影。数据源为豆瓣RSS。Triggers: 电影, 看什么, 推荐电影, 口碑榜, 即将上映, 今晚看啥, movie, douban, 豆瓣电影, 找电影, 新片
---

# 豆瓣电影查询

通过 Folo RSS API 获取豆瓣电影数据，支持口碑榜、即将上映、智能推荐。

## 脚本

`scripts/douban_movie.py` — 无需依赖，纯 Python 3 标准库。

## 用法

### 查看榜单

```bash
# 一周口碑榜（默认8部）
python3 scripts/douban_movie.py list weekly -v

# 即将上映
python3 scripts/douban_movie.py list coming -v

# 本周口碑榜（另一数据源）
python3 scripts/douban_movie.py list top -v

# 限制数量
python3 scripts/douban_movie.py list weekly -n 3 -v
```

### 筛选

```bash
# 7.5分以上
python3 scripts/douban_movie.py list weekly -r 7.5 -v

# 按类型：剧情、喜剧、动作、爱情、悬疑、科幻、动画、恐怖、犯罪...
python3 scripts/douban_movie.py list weekly -g 剧情 -v

# 关键词（搜标题、简介、导演、演员）
python3 scripts/douban_movie.py list weekly -k 赵婷 -v

# 组合筛选
python3 scripts/douban_movie.py list weekly -r 7.0 -g 剧情 -v
```

### 推荐电影

```bash
# 最高分推荐
python3 scripts/douban_movie.py recommend

# 随机推荐（今晚看啥）
python3 scripts/douban_movie.py recommend --lucky

# 带条件推荐
python3 scripts/douban_movie.py recommend -r 7.5 -g 喜剧
```

### 全部榜单一览

```bash
python3 scripts/douban_movie.py all -v
```

### JSON 输出（程序化使用）

```bash
python3 scripts/douban_movie.py json weekly -n 5
```

## 数据源

| Feed | 内容 | 更新频率 |
|------|------|---------|
| `weekly` | 一周口碑电影榜 | 每周五 |
| `coming` | 即将上映 | 实时 |
| `top` | 本周口碑榜 | 每周 |

## 响应策略

- 用户问"今晚看啥" → `recommend --lucky`
- 用户问"最近有什么好电影" → `list weekly -v`
- 用户问"有什么新片要上映" → `list coming -v`
- 用户问特定类型 → `list weekly -g <类型> -v`
- 用户要高分片 → `list weekly -r 8.0 -v` 或 `recommend -r 8.0`
