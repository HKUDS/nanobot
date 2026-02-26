# Upstream 同步 2026-02-20

## 上游新 commit 摘要

- fix: safety guard 对 URL 中 'format' 的误报
- fix: shell timeout 后 wait killed process 防止 fd 泄漏
- fix: Codex provider routing 对 GitHub Copilot models 的修复
- feat: 飞书支持发送图片/音频/文件
- fix: pin dependency version ranges（依赖版本上下界）
- chore: 移除网络依赖的测试文件

## 冲突文件及决策

### 1. pyproject.toml — 依赖版本

**冲突原因**：上游将所有依赖 pin 了上下界（如 `>=0.20.0,<1.0.0`），我们只有下界。

**决策**：采用上游的 pinned 版本方案。理由：
- 上下界 pin 法更安全，防止 major version 意外升级
- 上游移除了重复的 `socksio` 独立条目（`python-telegram-bot[socks]` 已包含）
- 我们有一个重复的 `mcp>=1.0.0` 条目需要去掉

### 2. nanobot/providers/litellm_provider.py — Codex routing 修复

**冲突原因**：上游新增 `_canonicalize_explicit_prefix` 静态方法，我们这边该位置为空。

**决策**：直接采用上游新增的方法。这是 bug fix，修复 GitHub Copilot models 的 provider routing 问题，我们没有对应的本地修改。

## 合并指令

```bash
cd ~/Developer/github/nanobot
git merge upstream/main
# 解决冲突后：
# pyproject.toml → 采用上游版本（incoming）
# litellm_provider.py → 采用上游版本（incoming），保留我们已有的代码
git add -A
git commit -m "merge upstream/main: pin deps, codex routing fix, feishu media, shell timeout fix"
python -m pytest tests/ -x --timeout=30
```
