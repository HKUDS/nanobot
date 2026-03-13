# Git Workflow Summary

This document summarizes the Git CLI commands used during the Zalo integration and the migration to the internal GitLab repository.

## 1. Staging & Committing (Zalo Integration)

To stage only the Zalo-related files (excluding RAG changes):

```bash
# Stage Zalo files (forced for ignored docs)
git add nanobot/channels/zalo.py \
        nanobot/channels/manager.py \
        nanobot/config/schema.py \
        nanobot/channels/base.py \
        nanobot/config/loader.py \
        pyproject.toml
git add -f docs/doc_zalo_integration.md

# Commit
git commit -m "feat: Add Zalo channel integration (Webhook mode)"
```

## 2. GitLab Remote Management

To add the internal GitLab remote and push the feature branch:

```bash
# Add GitLab remote
git remote add gitlab https://gitlab.sunteco.cloud/ai/sun_ai/bot_assitant/nano_bot.git

# Initial push (mapped to main)
git push gitlab feat/zalo-integration:main

# Correcting to master (Delete main, push to master)
git push gitlab --delete main
git push gitlab feat/zalo-integration:master
```

## 3. Handling Push Conflicts (Remote master protection)

If the remote `master` has an initial commit that conflicts with your local history:

```bash
# 1. Fetch remote tracking
git fetch gitlab master

# 2. Save your current uncommitted work
git stash

# 3. Pull and merge remote master (allow unrelated histories)
git pull gitlab master --allow-unrelated-histories --no-edit

# 4. Resolve conflicts (preferring local version)
git checkout --ours README.md
git add README.md
git commit -m "Merge remote master (initial commit)"

# 5. Push to remote master
git push gitlab feat/zalo-integration:master

# 6. Restore your stashed work
git stash pop
```

## 4. Switching to GitLab Master Locally

To create a local `master` branch that tracks your GitLab repository:

```bash
# 1. Stash current work
git stash

# 2. Checkout new local master from remote
git checkout -b master gitlab/master

# (Optional) Return to feature branch
git checkout feat/zalo-integration
git stash pop
```
