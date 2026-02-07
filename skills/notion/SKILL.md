# Notion Skill

## Description
Interact with the Notion API. Currently supports listing databases in your workspace.

## Commands
- **list-db**: List all databases and their titles.

## Usage
```bash
nanobot agent -m "notion list-db"
```

The skill reads `config.json` for the `api_key`. You can also set the environment variable `NOTION_API_KEY`.
