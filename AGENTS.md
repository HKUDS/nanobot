# 🛠️ Core Engineering Guidelines

You are currently inside the `~/.core/` directory. This is the source code of your own brain—a fork of the `HKUDS/nanobot` framework.

## 📐 Design Philosophy
- **Ultra-Lightweight:** The entire framework is under 4,000 lines of code. Keep it that way. Avoid adding heavy dependencies unless strictly necessary.
- **Pythonic:** Use Python 3.11+, enforce type hinting, and rely on `pydantic` v2 for data structures.

## ⚠️ Danger Zone
You are editing the code that is currently running you. 
- A syntax error will cause you to crash upon restart.
- Always use `ruff check .` to lint your code before restarting the service.

## 🌿 Git Workflow
This directory is a Git repository linked to a personal fork. 
When you successfully implement a new feature:
1. `git add .`
2. `git commit -m "feat: description of your awesome upgrade"`
3. `git push origin main`

By pushing to the fork, you ensure your upgrades are safely backed up and can later be submitted as a Pull Request to the upstream `HKUDS/nanobot` repository.
