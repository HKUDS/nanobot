# Contributing to nanobot - Step-by-Step Guide

This guide walks you through the complete process of contributing to nanobot, from creating an issue to submitting a pull request.

---

## � Quick Example

Here's what a **real contribution workflow** looks like:

```bash
# 1. Fork on GitHub and clone
git clone https://github.com/YOUR_USERNAME/nanobot.git
cd nanobot

# 2. Create a branch
git checkout -b fix/improve-docs

# 3. Make your changes
code README.md  # Edit files

# 4. Commit your work
git add README.md
git commit -m "docs: improve installation instructions"

# 5. Push to GitHub
git push origin fix/improve-docs

# 6. Go to GitHub and create a PR
# That's it! Wait for maintainers to review
```

**Output you'll see:**
```
remote: Create a pull request for 'fix/improve-docs' on GitHub by visiting:
remote:      https://github.com/YOUR_USERNAME/nanobot/pull/new/fix/improve-docs
```

---

## �📋 Table of Contents

1. [Fork the Repository](#1-fork-the-repository)
2. [Clone Your Fork](#2-clone-your-fork)
3. [Create an Issue (Optional)](#3-create-an-issue-optional)
4. [Create a Feature Branch](#4-create-a-feature-branch)
5. [Make Your Changes](#5-make-your-changes)
6. [Commit Your Changes](#6-commit-your-changes)
7. [Push to Your Fork](#7-push-to-your-fork)
8. [Create a Pull Request](#8-create-a-pull-request)
9. [Respond to Feedback](#9-respond-to-feedback)

---

## 1. Fork the Repository

**On GitHub:**
1. Go to https://github.com/HKUDS/nanobot
2. Click **Fork** (top right button)
3. This creates your own copy of the repo

**Result:** You now have `https://github.com/YOUR_USERNAME/nanobot`

---

## 2. Clone Your Fork

**In your terminal:**

```bash
git clone https://github.com/YOUR_USERNAME/nanobot.git
cd nanobot
git remote add upstream https://github.com/HKUDS/nanobot.git
```

**What this does:**
- `git clone` → Downloads your fork
- `git remote add upstream` → Links to the original repo (for staying updated)

---

## 3. Create an Issue (Optional)

**When to create an issue:**
- 🐛 Bug reports
- ✨ New features
- 🔧 Major changes
- 📚 Documentation improvements

**When NOT needed:**
- Typo fixes
- Small documentation updates
- Code cleanup

**On GitHub:**
1. Go to https://github.com/HKUDS/nanobot/issues
2. Click **New Issue**
3. Choose a template (Bug Report, Feature Request, etc.)
4. Fill in the details and submit

**Example Issue:**
```
Title: Improve uv installation documentation

## Problem
The current uv installation section uses Linux-only syntax and outdated workflow.

## Solution
Update docs to use modern `uv sync` and add Windows support.

## Why
This makes setup cross-platform compatible and clearer for new users.
```

**Note the issue number** (e.g., `#42`)

---

## 4. Create a Feature Branch

**Branch naming conventions:**
- `fix/` — Bug fixes
- `feature/` — New features
- `docs/` — Documentation
- `refactor/` — Code refactoring

**In your terminal:**

```bash
git checkout -b fix/improve-uv-docs
```

or (if you have an issue):

```bash
git checkout -b fix/issue-42-improve-uv-docs
```

---

## 5. Make Your Changes

Edit the files you need to change. For example:

```bash
# Edit README.md
code README.md

# Or edit multiple files
code README.md .gitignore
```

**Keep in mind:**
- Make focused changes (one feature per PR)
- Don't mix unrelated changes
- Test your changes locally

---

## 6. Commit Your Changes

**Check what changed:**

```bash
git status
```

**Stage your changes:**

```bash
git add README.md .gitignore
```

**Commit with a clear message:**

```bash
git commit -m "docs: improve uv installation instructions (cross-platform)"
```

**Commit message format:**
```
<type>: <description>

<optional body>
```

**Types:**
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `refactor:` Code refactoring
- `test:` Tests
- `chore:` Dependencies, config

**Examples:**
```bash
git commit -m "docs: fix uv installation syntax"
git commit -m "fix: handle edge case in message parsing"
git commit -m "feat: add web search tool"
```

---

## 7. Push to Your Fork

**Push your branch:**

```bash
git push origin fix/improve-uv-docs
```

**Result:** Your changes are now on GitHub

---

## 8. Create a Pull Request

**On GitHub:**

1. Go to https://github.com/YOUR_USERNAME/nanobot
2. You'll see a **"Compare & Pull Request"** button
3. Click it
4. Fill in the PR details:

**PR Title:**
```
docs: improve uv installation instructions (cross-platform)
```

**PR Description:**

```markdown
## Description
Improves the uv installation section in README.

## Changes
- Fixed uv installation to use modern `uv sync` instead of `uv pip install`
- Added cross-platform support (Windows and Linux/Mac)
- Clarified when to use `uv run` vs. activating venv
- Removed deprecated `uv venv` command

## Why
The original docs used Linux-only syntax and outdated workflow.
This makes it clear and cross-platform compatible.

## Closes
Fixes #42 (if you have an issue)
```

**Then:**
1. Select **Create pull request** (not draft)
2. Wait for maintainers to review

---

## 9. Respond to Feedback

**If maintainers ask for changes:**

1. Make the requested changes locally
2. Commit and push again:

```bash
git add .
git commit -m "docs: update based on feedback"
git push origin fix/improve-uv-docs
```

3. The PR automatically updates with your new commit

**If approved & merged:**
- Congrats! 🎉 Your contribution is live!
- You can delete the branch:

```bash
git branch -d fix/improve-uv-docs
git push origin --delete fix/improve-uv-docs
```

---

## 🔄 Keep Your Fork Updated

**Before starting new work, sync with the original repo:**

```bash
git fetch upstream
git rebase upstream/main
git push origin main
```

---

## ✅ Quick Reference

```bash
# 1. Fork on GitHub, then:
git clone https://github.com/YOUR_USERNAME/nanobot.git
cd nanobot
git remote add upstream https://github.com/HKUDS/nanobot.git

# 2. Create branch
git checkout -b fix/feature-name

# 3. Make changes
code README.md

# 4. Commit
git add .
git commit -m "type: description"

# 5. Push
git push origin fix/feature-name

# 6. Create PR on GitHub website
# 7. Wait for review & respond to feedback
```

---

## 🤝 Contributing Tips

- ✅ Read the project README and structure first
- ✅ Check existing PRs/issues to avoid duplicates
- ✅ Keep PRs focused (one feature per PR)
- ✅ Write clear commit messages
- ✅ Test your changes before pushing
- ✅ Be respectful and patient with feedback
- ✅ Have fun! 🚀

---

**Questions?** Check the [nanobot README](README.md) or ask the maintainers in your PR!

Happy contributing! 🐈

