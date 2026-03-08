---
name: gh-cli
description: GitHub CLI (gh) comprehensive reference for repositories, issues, pull requests, Actions, projects, releases, gists, codespaces, organizations, extensions, and all GitHub operations from the command line.
---

# GitHub CLI (gh)

Comprehensive reference for GitHub CLI (gh) - work seamlessly with GitHub from the command line.

**Version:** 2.85.0 (current as of January 2026)

## Prerequisites

### Installation

```bash
# macOS
brew install gh

# Linux
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh

# Windows
winget install --id GitHub.cli

# Verify installation
gh --version
```

### Authentication

```bash
# Interactive login (default: github.com)
gh auth login

# Login with specific hostname
gh auth login --hostname enterprise.internal

# Login with token
gh auth login --with-token < mytoken.txt

# Check authentication status
gh auth status

# Switch accounts
gh auth switch --hostname github.com --user username

# Logout
gh auth logout --hostname github.com --user username
```

### Setup Git Integration

```bash
# Configure git to use gh as credential helper
gh auth setup-git

# View active token
gh auth token

# Refresh authentication scopes
gh auth refresh --scopes write:org,read:public_key
```

## CLI Structure

```
gh                          # Root command
├── auth                    # Authentication
│   ├── login
│   ├── logout
│   ├── refresh
│   ├── setup-git
│   ├── status
│   ├── switch
│   └── token
├── browse                  # Open in browser
├── codespace               # GitHub Codespaces
│   ├── code
│   ├── cp
│   ├── create
│   ├── delete
│   ├── edit
│   ├── jupyter
│   ├── list
│   ├── logs
│   ├── ports
│   ├── rebuild
│   ├── ssh
│   ├── stop
│   └── view
├── gist                    # Gists
│   ├── clone
│   ├── create
│   ├── delete
│   ├── edit
│   ├── list
│   ├── rename
│   └── view
├── issue                   # Issues
│   ├── create
│   ├── list
│   ├── status
│   ├── close
│   ├── comment
│   ├── delete
│   ├── develop
│   ├── edit
│   ├── lock
│   ├── pin
│   ├── reopen
│   ├── transfer
│   ├── unlock
│   └── view
├── org                     # Organizations
│   └── list
├── pr                      # Pull Requests
│   ├── create
│   ├── list
│   ├── status
│   ├── checkout
│   ├── checks
│   ├── close
│   ├── comment
│   ├── diff
│   ├── edit
│   ├── lock
│   ├── merge
│   ├── ready
│   ├── reopen
│   ├── revert
│   ├── review
│   ├── unlock
│   ├── update-branch
│   └── view
├── project                 # Projects
│   ├── close
│   ├── copy
│   ├── create
│   ├── delete
│   ├── edit
│   ├── field-create
│   ├── field-delete
│   ├── field-list
│   ├── item-add
│   ├── item-archive
│   ├── item-create
│   ├── item-delete
│   ├── item-edit
│   ├── item-list
│   ├── link
│   ├── list
│   ├── mark-template
│   ├── unlink
│   └── view
├── release                 # Releases
│   ├── create
│   ├── list
│   ├── delete
│   ├── delete-asset
│   ├── download
│   ├── edit
│   ├── upload
│   ├── verify
│   ├── verify-asset
│   └── view
├── repo                    # Repositories
│   ├── create
│   ├── list
│   ├── archive
│   ├── autolink
│   ├── clone
│   ├── delete
│   ├── deploy-key
│   ├── edit
│   ├── fork
│   ├── gitignore
│   ├── license
│   ├── rename
│   ├── set-default
│   ├── sync
│   ├── unarchive
│   └── view
├── cache                   # Actions caches
│   ├── delete
│   └── list
├── run                     # Workflow runs
│   ├── cancel
│   ├── delete
│   ├── download
│   ├── list
│   ├── rerun
│   ├── view
│   └── watch
├── workflow                # Workflows
│   ├── disable
│   ├── enable
│   ├── list
│   ├── run
│   └── view
├── agent-task              # Agent tasks
├── alias                   # Command aliases
│   ├── delete
│   ├── import
│   ├── list
│   └── set
├── api                     # API requests
├── attestation             # Artifact attestations
│   ├── download
│   ├── trusted-root
│   └── verify
├── completion              # Shell completion
├── config                  # Configuration
│   ├── clear-cache
│   ├── get
│   ├── list
│   └── set
├── extension               # Extensions
│   ├── browse
│   ├── create
│   ├── exec
│   ├── install
│   ├── list
│   ├── remove
│   ├── search
│   └── upgrade
├── gpg-key                 # GPG keys
│   ├── add
│   ├── delete
│   └── list
├── label                   # Labels
│   ├── clone
│   ├── create
│   ├── delete
│   ├── edit
│   └── list
├── preview                 # Preview features
├── ruleset                 # Rulesets
│   ├── check
│   ├── list
│   └── view
├── search                  # Search
│   ├── code
│   ├── commits
│   ├── issues
│   ├── prs
│   └── repos
├── secret                  # Secrets
│   ├── delete
│   ├── list
│   └── set
├── ssh-key                 # SSH keys
│   ├── add
│   ├── delete
│   └── list
├── status                  # Status overview
└── variable                # Variables
    ├── delete
    ├── get
    ├── list
    └── set
```

## Configuration

### Global Configuration

```bash
# List all configuration
gh config list

# Get specific configuration value
gh config list git_protocol
gh config get editor

# Set configuration value
gh config set editor vim
gh config set git_protocol ssh
gh config set prompt disabled
gh config set pager "less -R"

# Clear configuration cache
gh config clear-cache
```

### Environment Variables

```bash
# GitHub token (for automation)
export GH_TOKEN=ghp_xxxxxxxxxxxx

# GitHub hostname
export GH_HOST=github.com

# Disable prompts
export GH_PROMPT_DISABLED=true

# Custom editor
export GH_EDITOR=vim

# Custom pager
export GH_PAGER=less

# HTTP timeout
export GH_TIMEOUT=30

# Custom repository (override default)
export GH_REPO=owner/repo

# Custom git protocol
export GH_ENTERPRISE_HOSTNAME=hostname
```

## Authentication (gh auth)

### Login

```bash
# Interactive login
gh auth login

# Web-based authentication
gh auth login --web

# With clipboard for OAuth code
gh auth login --web --clipboard

# With specific git protocol
gh auth login --git-protocol ssh

# With custom hostname (GitHub Enterprise)
gh auth login --hostname enterprise.internal

# Login with token from stdin
gh auth login --with-token < token.txt

# Insecure storage (plain text)
gh auth login --insecure-storage
```

### Status

```bash
# Show all authentication status
gh auth status

# Show active account only
gh auth status --active

# Show specific hostname
gh auth status --hostname github.com

# Show token in output
gh auth status --show-token

# JSON output
gh auth status --json hosts

# Filter with jq
gh auth status --json hosts --jq '.hosts | add'
```

### Switch Accounts

```bash
# Interactive switch
gh auth switch

# Switch to specific user/host
gh auth switch --hostname github.com --user monalisa
```

### Token

```bash
# Print authentication token
gh auth token

# Token for specific host/user
gh auth token --hostname github.com --user monalisa
```

### Refresh

```bash
# Refresh credentials
gh auth refresh

# Add scopes
gh auth refresh --scopes write:org,read:public_key

# Remove scopes
gh auth refresh --remove-scopes delete_repo

# Reset to default scopes
gh auth refresh --reset-scopes

# With clipboard
gh auth refresh --clipboard
```

### Setup Git

```bash
# Setup git credential helper
gh auth setup-git

# Setup for specific host
gh auth setup-git --hostname enterprise.internal

# Force setup even if host not known
gh auth setup-git --hostname enterprise.internal --force
```

## Browse (gh browse)

```bash
# Open repository in browser
gh browse

# Open specific path
gh browse script/
gh browse main.go:312

# Open issue or PR
gh browse 123

# Open commit
gh browse 77507cd94ccafcf568f8560cfecde965fcfa63

# Open with specific branch
gh browse main.go --branch bug-fix

# Open different repository
gh browse --repo owner/repo

# Open specific pages
gh browse --actions       # Actions tab
gh browse --projects      # Projects tab
gh browse --releases      # Releases tab
gh browse --settings      # Settings page
gh browse --wiki          # Wiki page

# Print URL instead of opening
gh browse --no-browser
```

## Repositories (gh repo)

### Create Repository

```bash
# Create new repository
gh repo create my-repo

# Create with description
gh repo create my-repo --description "My awesome project"

# Create public repository
gh repo create my-repo --public

# Create private repository
gh repo create my-repo --private

# Create with homepage
gh repo create my-repo --homepage https://example.com

# Create with license
gh repo create my-repo --license mit

# Create with gitignore
gh repo create my-repo --gitignore python

# Initialize as template repository
gh repo create my-repo --template

# Create repository in organization
gh repo create org/my-repo

# Create without cloning locally
gh repo create my-repo --source=.

# Disable issues
gh repo create my-repo --disable-issues

# Disable wiki
gh repo create my-repo --disable-wiki
```

### Clone Repository

```bash
# Clone repository
gh repo clone owner/repo

# Clone to specific directory
gh repo clone owner/repo my-directory

# Clone with different branch
gh repo clone owner/repo --branch develop
```

### List Repositories

```bash
# List all repositories
gh repo list

# List repositories for owner
gh repo list owner

# Limit results
gh repo list --limit 50

# Public repositories only
gh repo list --public

# Source repositories only (not forks)
gh repo list --source

# JSON output
gh repo list --json name,visibility,owner

# Table output
gh repo list --limit 100 | tail -n +2

# Filter with jq
gh repo list --json name --jq '.[].name'
```

### View Repository

```bash
# View repository details
gh repo view

# View specific repository
gh repo view owner/repo

# JSON output
gh repo view --json name,description,defaultBranchRef

# View in browser
gh repo view --web
```

### Edit Repository

```bash
# Edit description
gh repo edit --description "New description"

# Set homepage
gh repo edit --homepage https://example.com

# Change visibility
gh repo edit --visibility private
gh repo edit --visibility public

# Enable/disable features
gh repo edit --enable-issues
gh repo edit --disable-issues
gh repo edit --enable-wiki
gh repo edit --disable-wiki
gh repo edit --enable-projects
gh repo edit --disable-projects

# Set default branch
gh repo edit --default-branch main

# Rename repository
gh repo rename new-name

# Archive repository
gh repo archive
gh repo unarchive
```

### Delete Repository

```bash
# Delete repository
gh repo delete owner/repo

# Confirm without prompt
gh repo delete owner/repo --yes
```

### Fork Repository

```bash
# Fork repository
gh repo fork owner/repo

# Fork to organization
gh repo fork owner/repo --org org-name

# Clone after forking
gh repo fork owner/repo --clone

# Remote name for fork
gh repo fork owner/repo --remote-name upstream
```

### Sync Fork

```bash
# Sync fork with upstream
gh repo sync

# Sync specific branch
gh repo sync --branch feature

# Force sync
gh repo sync --force
```

### Set Default Repository

```bash
# Set default repository for current directory
gh repo set-default

# Set default explicitly
gh repo set-default owner/repo

# Unset default
gh repo set-default --unset
```

### Repository Autolinks

```bash
# List autolinks
gh repo autolink list

# Add autolink
gh repo autolink add \
  --key-prefix JIRA- \
  --url-template https://jira.example.com/browse/<num>

# Delete autolink
gh repo autolink delete 12345
```

### Repository Deploy Keys

```bash
# List deploy keys
gh repo deploy-key list

# Add deploy key
gh repo deploy-key add ~/.ssh/id_rsa.pub \
  --title "Production server" \
  --read-only

# Delete deploy key
gh repo deploy-key delete 12345
```

### Gitignore and License

```bash
# View gitignore template
gh repo gitignore

# View license template
gh repo license mit

# License with full name
gh repo license mit --fullname "John Doe"
```

## Issues (gh issue)

### Create Issue

```bash
# Create issue interactively
gh issue create

# Create with title
gh issue create --title "Bug: Login not working"

# Create with title and body
gh issue create \
  --title "Bug: Login not working" \
  --body "Steps to reproduce..."

# Create with body from file
gh issue create --body-file issue.md

# Create with labels
gh issue create --title "Fix bug" --labels bug,high-priority

# Create with assignees
gh issue create --title "Fix bug" --assignee user1,user2

# Create in specific repository
gh issue create --repo owner/repo --title "Issue title"

# Create issue from web
gh issue create --web
```

### List Issues

```bash
# List all open issues
gh issue list

# List all issues (including closed)
gh issue list --state all

# List closed issues
gh issue list --state closed

# Limit results
gh issue list --limit 50

# Filter by assignee
gh issue list --assignee username
gh issue list --assignee @me

# Filter by labels
gh issue list --labels bug,enhancement

# Filter by milestone
gh issue list --milestone "v1.0"

# Search/filter
gh issue list --search "is:open is:issue label:bug"

# JSON output
gh issue list --json number,title,state,author

# Table view
gh issue list --json number,title,labels --jq '.[] | [.number, .title, .labels[].name] | @tsv'

# Show comments count
gh issue list --json number,title,comments --jq '.[] | [.number, .title, .comments]'

# Sort by
gh issue list --sort created --order desc
```

### View Issue

```bash
# View issue
gh issue view 123

# View with comments
gh issue view 123 --comments

# View in browser
gh issue view 123 --web

# JSON output
gh issue view 123 --json title,body,state,labels,comments

# View specific fields
gh issue view 123 --json title --jq '.title'
```

### Edit Issue

```bash
# Edit interactively
gh issue edit 123

# Edit title
gh issue edit 123 --title "New title"

# Edit body
gh issue edit 123 --body "New description"

# Add labels
gh issue edit 123 --add-label bug,high-priority

# Remove labels
gh issue edit 123 --remove-label stale

# Add assignees
gh issue edit 123 --add-assignee user1,user2

# Remove assignees
gh issue edit 123 --remove-assignee user1

# Set milestone
gh issue edit 123 --milestone "v1.0"
```

### Close/Reopen Issue

```bash
# Close issue
gh issue close 123

# Close with comment
gh issue close 123 --comment "Fixed in PR #456"

# Reopen issue
gh issue reopen 123
```

### Comment on Issue

```bash
# Add comment
gh issue comment 123 --body "This looks good!"

# Edit comment
gh issue comment 123 --edit 456789 --body "Updated comment"

# Delete comment
gh issue comment 123 --delete 456789
```

### Issue Status

```bash
# Show issue status summary
gh issue status

# Status for specific repository
gh issue status --repo owner/repo
```

### Pin/Unpin Issues

```bash
# Pin issue (pinned to repo dashboard)
gh issue pin 123

# Unpin issue
gh issue unpin 123
```

### Lock/Unlock Issue

```bash
# Lock conversation
gh issue lock 123

# Lock with reason
gh issue lock 123 --reason off-topic

# Unlock
gh issue unlock 123
```

### Transfer Issue

```bash
# Transfer to another repository
gh issue transfer 123 --repo owner/new-repo
```

### Delete Issue

```bash
# Delete issue
gh issue delete 123

# Confirm without prompt
gh issue delete 123 --yes
```

### Develop Issue (Draft PR)

```bash
# Create draft PR from issue
gh issue develop 123

# Create in specific branch
gh issue develop 123 --branch fix/issue-123

# Create with base branch
gh issue develop 123 --base main
```

## Pull Requests (gh pr)

### Create Pull Request

```bash
# Create PR interactively
gh pr create

# Create with title
gh pr create --title "Feature: Add new functionality"

# Create with title and body
gh pr create \
  --title "Feature: Add new functionality" \
  --body "This PR adds..."

# Fill body from template
gh pr create --body-file .github/PULL_REQUEST_TEMPLATE.md

# Set base branch
gh pr create --base main

# Set head branch (default: current branch)
gh pr create --head feature-branch

# Create draft PR
gh pr create --draft

# Add assignees
gh pr create --assignee user1,user2

# Add reviewers
gh pr create --reviewer user1,user2

# Add labels
gh pr create --labels enhancement,feature

# Link to issue
gh pr create --issue 123

# Create in specific repository
gh pr create --repo owner/repo

# Open in browser after creation
gh pr create --web
```

### List Pull Requests

```bash
# List open PRs
gh pr list

# List all PRs
gh pr list --state all

# List merged PRs
gh pr list --state merged

# List closed (not merged) PRs
gh pr list --state closed

# Filter by head branch
gh pr list --head feature-branch

# Filter by base branch
gh pr list --base main

# Filter by author
gh pr list --author username
gh pr list --author @me

# Filter by assignee
gh pr list --assignee username

# Filter by labels
gh pr list --labels bug,enhancement

# Limit results
gh pr list --limit 50

# Search
gh pr list --search "is:open is:pr label:review-required"

# JSON output
gh pr list --json number,title,state,author,headRefName

# Show check status
gh pr list --json number,title,statusCheckRollup --jq '.[] | [.number, .title, .statusCheckRollup[]?.status]'

# Sort by
gh pr list --sort created --order desc
```

### View Pull Request

```bash
# View PR
gh pr view 123

# View with comments
gh pr view 123 --comments

# View in browser
gh pr view 123 --web

# JSON output
gh pr view 123 --json title,body,state,author,commits,files

# View diff
gh pr view 123 --json files --jq '.files[].path'

# View with jq query
gh pr view 123 --json title,state --jq '"\(.title): \(.state)"'
```

### Checkout Pull Request

```bash
# Checkout PR branch
gh pr checkout 123

# Checkout with specific branch name
gh pr checkout 123 --branch name-123

# Force checkout
gh pr checkout 123 --force
```

### Diff Pull Request

```bash
# View PR diff
gh pr diff 123

# View diff with color
gh pr diff 123 --color always

# Output to file
gh pr diff 123 > pr-123.patch

# View diff of specific files
gh pr diff 123 --name-only
```

### Merge Pull Request

```bash
# Merge PR
gh pr merge 123

# Merge with specific method
gh pr merge 123 --merge
gh pr merge 123 --squash
gh pr merge 123 --rebase

# Delete branch after merge
gh pr merge 123 --delete-branch

# Merge with comment
gh pr merge 123 --subject "Merge PR #123" --body "Merging feature"

# Merge draft PR
gh pr merge 123 --admin

# Force merge (skip checks)
gh pr merge 123 --admin
```

### Close Pull Request

```bash
# Close PR (as draft, not merge)
gh pr close 123

# Close with comment
gh pr close 123 --comment "Closing due to..."
```

### Reopen Pull Request

```bash
# Reopen closed PR
gh pr reopen 123
```

### Edit Pull Request

```bash
# Edit interactively
gh pr edit 123

# Edit title
gh pr edit 123 --title "New title"

# Edit body
gh pr edit 123 --body "New description"

# Add labels
gh pr edit 123 --add-label bug,enhancement

# Remove labels
gh pr edit 123 --remove-label stale

# Add assignees
gh pr edit 123 --add-assignee user1,user2

# Remove assignees
gh pr edit 123 --remove-assignee user1

# Add reviewers
gh pr edit 123 --add-reviewer user1,user2

# Remove reviewers
gh pr edit 123 --remove-reviewer user1

# Mark as ready for review
gh pr edit 123 --ready
```

### Ready for Review

```bash
# Mark draft PR as ready
gh pr ready 123
```

### Pull Request Checks

```bash
# View PR checks
gh pr checks 123

# Watch checks in real-time
gh pr checks 123 --watch

# Watch interval (seconds)
gh pr checks 123 --watch --interval 5
```

### Comment on Pull Request

```bash
# Add comment
gh pr comment 123 --body "Looks good!"

# Comment on specific line
gh pr comment 123 --body "Fix this" \
  --repo owner/repo \
  --head-owner owner --head-branch feature

# Edit comment
gh pr comment 123 --edit 456789 --body "Updated"

# Delete comment
gh pr comment 123 --delete 456789
```

### Review Pull Request

```bash
# Review PR (opens editor)
gh pr review 123

# Approve PR
gh pr review 123 --approve \
  --approve-body "LGTM!"

# Request changes
gh pr review 123 --request-changes \
  --body "Please fix these issues"

# Comment on PR
gh pr review 123 --comment --body "Some thoughts..."

# Dismiss review
gh pr review 123 --dismiss
```

### Update Branch

```bash
# Update PR branch with latest base branch
gh pr update-branch 123

# Force update
gh pr update-branch 123 --force

# Use merge strategy
gh pr update-branch 123 --merge
```

### Lock/Unlock Pull Request

```bash
# Lock PR conversation
gh pr lock 123

# Lock with reason
gh pr lock 123 --reason off-topic

# Unlock
gh pr unlock 123
```

### Revert Pull Request

```bash
# Revert merged PR
gh pr revert 123

# Revert with specific branch name
gh pr revert 123 --branch revert-pr-123
```

### Pull Request Status

```bash
# Show PR status summary
gh pr status

# Status for specific repository
gh pr status --repo owner/repo
```

## GitHub Actions

### Workflow Runs (gh run)

```bash
# List workflow runs
gh run list

# List for specific workflow
gh run list --workflow "ci.yml"

# List for specific branch
gh run list --branch main

# Limit results
gh run list --limit 20

# JSON output
gh run list --json databaseId,status,conclusion,headBranch

# View run details
gh run view 123456789

# View run with verbose logs
gh run view 123456789 --log

# View specific job
gh run view 123456789 --job 987654321

# View in browser
gh run view 123456789 --web

# Watch run in real-time
gh run watch 123456789

# Watch with interval
gh run watch 123456789 --interval 5

# Rerun failed run
gh run rerun 123456789

# Rerun specific job
gh run rerun 123456789 --job 987654321

# Cancel run
gh run cancel 123456789

# Delete run
gh run delete 123456789

# Download run artifacts
gh run download 123456789

# Download specific artifact
gh run download 123456789 --name build

# Download to directory
gh run download 123456789 --dir ./artifacts
```

### Workflows (gh workflow)

```bash
# List workflows
gh workflow list

# View workflow details
gh workflow view ci.yml

# View workflow YAML
gh workflow view ci.yml --yaml

# View in browser
gh workflow view ci.yml --web

# Enable workflow
gh workflow enable ci.yml

# Disable workflow
gh workflow disable ci.yml

# Run workflow manually
gh workflow run ci.yml

# Run with inputs
gh workflow run ci.yml \
  --raw-field \
  version="1.0.0" \
  environment="production"

# Run from specific branch
gh workflow run ci.yml --ref develop
```

### Action Caches (gh cache)

```bash
# List caches
gh cache list

# List for specific branch
gh cache list --branch main

# List with limit
gh cache list --limit 50

# Delete cache
gh cache delete 123456789

# Delete all caches
gh cache delete --all
```

### Action Secrets (gh secret)

```bash
# List secrets
gh secret list

# Set secret (prompts for value)
gh secret set MY_SECRET

# Set secret from environment
echo "$MY_SECRET" | gh secret set MY_SECRET

# Set secret for specific environment
gh secret set MY_SECRET --env production

# Set secret for organization
gh secret set MY_SECRET --org orgname

# Delete secret
gh secret delete MY_SECRET

# Delete from environment
gh secret delete MY_SECRET --env production
```

### Action Variables (gh variable)

```bash
# List variables
gh variable list

# Set variable
gh variable set MY_VAR "some-value"

# Set variable for environment
gh variable set MY_VAR "value" --env production

# Set variable for organization
gh variable set MY_VAR "value" --org orgname

# Get variable value
gh variable get MY_VAR

# Delete variable
gh variable delete MY_VAR

# Delete from environment
gh variable delete MY_VAR --env production
```

## Projects (gh project)

```bash
# List projects
gh project list

# List for owner
gh project list --owner owner

# Open projects
gh project list --open

# View project
gh project view 123

# View project items
gh project view 123 --format json

# Create project
gh project create --title "My Project"

# Create in organization
gh project create --title "Project" --org orgname

# Create with readme
gh project create --title "Project" --readme "Description here"

# Edit project
gh project edit 123 --title "New Title"

# Delete project
gh project delete 123

# Close project
gh project close 123

# Copy project
gh project copy 123 --owner target-owner --title "Copy"

# Mark template
gh project mark-template 123

# List fields
gh project field-list 123

# Create field
gh project field-create 123 --title "Status" --datatype single_select

# Delete field
gh project field-delete 123 --id 456

# List items
gh project item-list 123

# Create item
gh project item-create 123 --title "New item"

# Add item to project
gh project item-add 123 --owner-owner --repo repo --issue 456

# Edit item
gh project item-edit 123 --id 456 --title "Updated title"

# Delete item
gh project item-delete 123 --id 456

# Archive item
gh project item-archive 123 --id 456

# Link items
gh project link 123 --id 456 --link-id 789

# Unlink items
gh project unlink 123 --id 456 --link-id 789

# View project in browser
gh project view 123 --web
```

## Releases (gh release)

```bash
# List releases
gh release list

# View latest release
gh release view

# View specific release
gh release view v1.0.0

# View in browser
gh release view v1.0.0 --web

# Create release
gh release create v1.0.0 \
  --notes "Release notes here"

# Create release with notes from file
gh release create v1.0.0 --notes-file notes.md

# Create release with target
gh release create v1.0.0 --target main

# Create release as draft
gh release create v1.0.0 --draft

# Create pre-release
gh release create v1.0.0 --prerelease

# Create release with title
gh release create v1.0.0 --title "Version 1.0.0"

# Upload asset to release
gh release upload v1.0.0 ./file.tar.gz

# Upload multiple assets
gh release upload v1.0.0 ./file1.tar.gz ./file2.tar.gz

# Upload with label (casing sensitive)
gh release upload v1.0.0 ./file.tar.gz --casing

# Delete release
gh release delete v1.0.0

# Delete with cleanup tag
gh release delete v1.0.0 --yes

# Delete specific asset
gh release delete-asset v1.0.0 file.tar.gz

# Download release assets
gh release download v1.0.0

# Download specific asset
gh release download v1.0.0 --pattern "*.tar.gz"

# Download to directory
gh release download v1.0.0 --dir ./downloads

# Download archive (zip/tar)
gh release download v1.0.0 --archive zip

# Edit release
gh release edit v1.0.0 --notes "Updated notes"

# Verify release signature
gh release verify v1.0.0

# Verify specific asset
gh release verify-asset v1.0.0 file.tar.gz
```

## Gists (gh gist)

```bash
# List gists
gh gist list

# List all gists (including private)
gh gist list --public

# Limit results
gh gist list --limit 20

# View gist
gh gist view abc123

# View gist files
gh gist view abc123 --files

# Create gist
gh gist create script.py

# Create gist with description
gh gist create script.py --desc "My script"

# Create public gist
gh gist create script.py --public

# Create multi-file gist
gh gist create file1.py file2.py

# Create from stdin
echo "print('hello')" | gh gist create

# Edit gist
gh gist edit abc123

# Delete gist
gh gist delete abc123

# Rename gist file
gh gist rename abc123 --filename old.py new.py

# Clone gist
gh gist clone abc123

# Clone to directory
gh gist clone abc123 my-directory
```

## Codespaces (gh codespace)

```bash
# List codespaces
gh codespace list

# Create codespace
gh codespace create

# Create with specific repository
gh codespace create --repo owner/repo

# Create with branch
gh codespace create --branch develop

# Create with specific machine
gh codespace create --machine premiumLinux

# View codespace details
gh codespace view

# SSH into codespace
gh codespace ssh

# SSH with specific command
gh codespace ssh --command "cd /workspaces && ls"

# Open codespace in browser
gh codespace code

# Open in VS Code
gh codespace code --codec

# Open with specific path
gh codespace code --path /workspaces/repo

# Stop codespace
gh codespace stop

# Delete codespace
gh codespace delete

# View logs
gh codespace logs

--tail 100

# View ports
gh codespace ports

# Forward port
gh codespace cp 8080:8080

# Rebuild codespace
gh codespace rebuild

# Edit codespace
gh codespace edit --machine standardLinux

# Jupyter support
gh codespace jupyter

# Copy files to/from codespace
gh codespace cp file.txt :/workspaces/file.txt
gh codespace cp :/workspaces/file.txt ./file.txt
```

## Organizations (gh org)

```bash
# List organizations
gh org list

# List for user
gh org list --user username

# JSON output
gh org list --json login,name,description

# View organization
gh org view orgname

# View organization members
gh org view orgname --json members --jq '.members[] | .login'
```

## Search (gh search)

```bash
# Search code
gh search code "TODO"

# Search in specific repository
gh search code "TODO" --repo owner/repo

# Search commits
gh search commits "fix bug"

# Search issues
gh search issues "label:bug state:open"

# Search PRs
gh search prs "is:open is:pr review:required"

# Search repositories
gh search repos "stars:>1000 language:python"

# Limit results
gh search repos "topic:api" --limit 50

# JSON output
gh search repos "stars:>100" --json name,description,stargazers

# Order results
gh search repos "language:rust" --order desc --sort stars

# Search with extensions
gh search code "import" --extension py

# Web search (open in browser)
gh search prs "is:open" --web
```

## Labels (gh label)

```bash
# List labels
gh label list

# Create label
gh label create bug --color "d73a4a" --description "Something isn't working"

# Create with hex color
gh label create enhancement --color "#a2eeef"

# Edit label
gh label edit bug --name "bug-report" --color "ff0000"

# Delete label
gh label delete bug

# Clone labels from repository
gh label clone owner/repo

# Clone to specific repository
gh label clone owner/repo --repo target/repo
```

## SSH Keys (gh ssh-key)

```bash
# List SSH keys
gh ssh-key list

# Add SSH key
gh ssh-key add ~/.ssh/id_rsa.pub --title "My laptop"

# Add key with type
gh ssh-key add ~/.ssh/id_ed25519.pub --type "authentication"

# Delete SSH key
gh ssh-key delete 12345

# Delete by title
gh ssh-key delete --title "My laptop"
```

## GPG Keys (gh gpg-key)

```bash
# List GPG keys
gh gpg-key list

# Add GPG key
gh gpg-key add ~/.ssh/id_rsa.pub

# Delete GPG key
gh gpg-key delete 12345

# Delete by key ID
gh gpg-key delete ABCD1234
```

## Status (gh status)

```bash
# Show status overview
gh status

# Status for specific repositories
gh status --repo owner/repo

# JSON output
gh status --json
```

## Configuration (gh config)

```bash
# List all config
gh config list

# Get specific value
gh config get editor

# Set value
gh config set editor vim

# Set git protocol
gh config set git_protocol ssh

# Clear cache
gh config clear-cache

# Set prompt behavior
gh config set prompt disabled
gh config set prompt enabled
```

## Extensions (gh extension)

```bash
# List installed extensions
gh extension list

# Search extensions
gh extension search github

# Install extension
gh extension install owner/extension-repo

# Install from branch
gh extension install owner/extension-repo --branch develop

# Upgrade extension
gh extension upgrade extension-name

# Remove extension
gh extension remove extension-name

# Create new extension
gh extension create my-extension

# Browse extensions
gh extension browse

# Execute extension command
gh extension exec my-extension --arg value
```

## Aliases (gh alias)

```bash
# List aliases
gh alias list

# Set alias
gh alias set prview 'pr view --web'

# Set shell alias
gh alias set co 'pr checkout' --shell

# Delete alias
gh alias delete prview

# Import aliases
gh alias import ./aliases.sh
```

## API Requests (gh api)

```bash
# Make API request
gh api /user

# Request with method
gh api --method POST /repos/owner/repo/issues \
  --field title="Issue title" \
  --field body="Issue body"

# Request with headers
gh api /user \
  --header "Accept: application/vnd.github.v3+json"

# Request with pagination
gh api /user/repos --paginate

# Raw output (no formatting)
gh api /user --raw

# Include headers in output
gh api /user --include

# Silent mode (no progress output)
gh api /user --silent

# Input from file
gh api --input request.json

# jq query on response
gh api /user --jq '.login'

# Field from response
gh api /repos/owner/repo --jq '.stargazers_count'

# GitHub Enterprise
gh api /user --hostname enterprise.internal

# GraphQL query
gh api graphql \
  -f query='
  {
    viewer {
      login
      repositories(first: 5) {
        nodes {
          name
        }
      }
    }
  }'
```

## Rulesets (gh ruleset)

```bash
# List rulesets
gh ruleset list

# View ruleset
gh ruleset view 123

# Check ruleset
gh ruleset check --branch feature

# Check specific repository
gh ruleset check --repo owner/repo --branch main
```

## Attestations (gh attestation)

```bash
# Download attestation
gh attestation download owner/repo \
  --artifact-id 123456

# Verify attestation
gh attestation verify owner/repo

# Get trusted root
gh attestation trusted-root
```

## Completion (gh completion)

```bash
# Generate shell completion
gh completion -s bash > ~/.gh-complete.bash
gh completion -s zsh > ~/.gh-complete.zsh
gh completion -s fish > ~/.gh-complete.fish
gh completion -s powershell > ~/.gh-complete.ps1

# Shell-specific instructions
gh completion --shell=bash
gh completion --shell=zsh
```

## Preview (gh preview)

```bash
# List preview features
gh preview

# Run preview script
gh preview prompter
```

## Agent Tasks (gh agent-task)

```bash
# List agent tasks
gh agent-task list

# View agent task
gh agent-task view 123

# Create agent task
gh agent-task create --description "My task"
```

## Global Flags

| Flag                       | Description                            |
| -------------------------- | -------------------------------------- |
| `--help` / `-h`            | Show help for command                  |
| `--version`                | Show gh version                        |
| `--repo [HOST/]OWNER/REPO` | Select another repository              |
| `--hostname HOST`          | GitHub hostname                        |
| `--jq EXPRESSION`          | Filter JSON output                     |
| `--json FIELDS`            | Output JSON with specified fields      |
| `--template STRING`        | Format JSON using Go template          |
| `--web`                    | Open in browser                        |
| `--paginate`               | Make additional API calls              |
| `--verbose`                | Show verbose output                    |
| `--debug`                  | Show debug output                      |
| `--timeout SECONDS`        | Maximum API request duration           |
| `--cache CACHE`            | Cache control (default, force, bypass) |

## Output Formatting

### JSON Output

```bash
# Basic JSON
gh repo view --json name,description

# Nested fields
gh repo view --json owner,name --jq '.owner.login + "/" + .name'

# Array operations
gh pr list --json number,title --jq '.[] | select(.number > 100)'

# Complex queries
gh issue list --json number,title,labels \
  --jq '.[] | {number, title: .title, tags: [.labels[].name]}'
```

### Template Output

```bash
# Custom template
gh repo view \
  --template '{{.name}}: {{.description}}'

# Multiline template
gh pr view 123 \
  --template 'Title: {{.title}}
Author: {{.author.login}}
State: {{.state}}
'
```

## Common Workflows

### Create PR from Issue

```bash
# Create branch from issue
gh issue develop 123 --branch feature/issue-123

# Make changes, commit, push
git add .
git commit -m "Fix issue #123"
git push

# Create PR linking to issue
gh pr create --title "Fix #123" --body "Closes #123"
```

### Bulk Operations

```bash
# Close multiple issues
gh issue list --search "label:stale" \
  --json number \
  --jq '.[].number' | \
  xargs -I {} gh issue close {} --comment "Closing as stale"

# Add label to multiple PRs
gh pr list --search "review:required" \
  --json number \
  --jq '.[].number' | \
  xargs -I {} gh pr edit {} --add-label needs-review
```

### Repository Setup Workflow

```bash
# Create repository with initial setup
gh repo create my-project --public \
  --description "My awesome project" \
  --clone \
  --gitignore python \
  --license mit

cd my-project

# Set up branches
git checkout -b develop
git push -u origin develop

# Create labels
gh label create bug --color "d73a4a" --description "Bug report"
gh label create enhancement --color "a2eeef" --description "Feature request"
gh label create documentation --color "0075ca" --description "Documentation"
```

### CI/CD Workflow

```bash
# Run workflow and wait
RUN_ID=$(gh workflow run ci.yml --ref main --jq '.databaseId')

# Watch the run
gh run watch "$RUN_ID"

# Download artifacts on completion
gh run download "$RUN_ID" --dir ./artifacts
```

### Fork Sync Workflow

```bash
# Fork repository
gh repo fork original/repo --clone

cd repo

# Add upstream remote
git remote add upstream https://github.com/original/repo.git

# Sync fork
gh repo sync

# Or manual sync
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

## Environment Setup

### Shell Integration

```bash
# Add to ~/.bashrc or ~/.zshrc
eval "$(gh completion -s bash)"  # or zsh/fish

# Create useful aliases
alias gs='gh status'
alias gpr='gh pr view --web'
alias gir='gh issue view --web'
alias gco='gh pr checkout'
```

### Git Configuration

```bash
# Use gh as credential helper
gh auth setup-git

# Set gh as default for repo operations
git config --global credential.helper 'gh !gh auth setup-git'

# Or manually
git config --global credential.helper github
```

## Best Practices

1. **Authentication**: Use environment variables for automation

   ```bash
   export GH_TOKEN=$(gh auth token)
   ```

2. **Default Repository**: Set default to avoid repetition

   ```bash
   gh repo set-default owner/repo
   ```

3. **JSON Parsing**: Use jq for complex data extraction

   ```bash
   gh pr list --json number,title --jq '.[] | select(.title | contains("fix"))'
   ```

4. **Pagination**: Use --paginate for large result sets

   ```bash
   gh issue list --state all --paginate
   ```

5. **Caching**: Use cache control for frequently accessed data
   ```bash
   gh api /user --cache force
   ```

## Getting Help

```bash
# General help
gh --help

# Command help
gh pr --help
gh issue create --help

# Help topics
gh help formatting
gh help environment
gh help exit-codes
gh help accessibility
```

## References

- Official Manual: https://cli.github.com/manual/
- GitHub Docs: https://docs.github.com/en/github-cli
- REST API: https://docs.github.com/en/rest
- GraphQL API: https://docs.github.com/en/graphql
