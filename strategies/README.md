# QuantBot 策略仓库

此目录存储量化策略代码，使用 Git 进行版本管理。

## 目录结构

```
strategies/
├── active/              # 当前运行的主力策略
│   ├── north_momentum.py
│   └── README.md
├── experimental/        # 实验中的策略
├── archive/             # 已废弃但保留的策略
├── backtest_results/   # 回测结果（不纳入 Git）
└── .gitignore
```

## Git 工作流

### 分支说明

| 分支 | 用途 |
|------|------|
| main | 当前主力策略 |
| candidate/* | 候选改进版本 |
| archive/* | 已废弃策略（保留参考） |

### 常用命令

```bash
# 初始化（首次）
git init
git add .
git commit -m "Initial commit: 策略仓库初始化"

# 创建实验分支
git checkout -b candidate/north-momentum-v4

# 提交修改
git add north_momentum.py
git commit -m "feat: 加入震荡过滤条件"

# 合并到主力
git checkout main
git merge candidate/north-momentum-v4

# 查看历史
git log --oneline
git log --graph
```

### 提交规范

```
feat:     新增策略逻辑
fix:      修正 bug
optimize: 参数优化
learn:    从外部学习改进
revert:   回退版本
```

## 配置

策略路径：`~/.nanobot/strategies`

通过 `strategy_git` Tool 管理。
