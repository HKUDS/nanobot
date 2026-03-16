---
name: feishu-api
description: "Use Feishu/Lark platform APIs: create/read/edit documents, spreadsheets, list chats and members. Requires the Feishu channel to be enabled."
metadata: '{"nanobot":{"emoji":"📝"}}'
---

# Feishu API Skill

Use the `feishu_*` tools to interact with the Feishu/Lark platform beyond simple messaging. These tools are available when the Feishu channel is enabled and configured.

## Prerequisites

- Feishu channel must be enabled in nanobot config with valid `app_id` and `app_secret`
- The Feishu app must have the required API scopes enabled in the Feishu Open Platform console:
  - `im:chat:readonly` — for listing chats
  - `im:chat.member:readonly` — for listing chat members
  - `docx:document` — for creating and reading documents
  - `sheets:spreadsheet` — for creating, reading, and writing spreadsheets

## Discovery

Use `channel_info` to check if the Feishu channel is enabled and see which tools are available.

## Available Tools

### Chat Operations

- `feishu_list_chats` — List all chats/groups the bot is a member of
  - Optional: `page_size` (default 50, max 100)
  - Returns: chat name, chat_id, and type for each chat

- `feishu_list_chat_members` — List members of a specific chat
  - Required: `chat_id`
  - Optional: `page_size` (default 50)
  - Returns: member name, id, and type

### Document Operations

- `feishu_create_doc` — Create a new Feishu document
  - Required: `title`
  - Optional: `folder_token` (places the doc in a specific folder)
  - Returns: document URL and ID

- `feishu_read_doc` — Read the text content of a Feishu document
  - Required: `document_id` (the ID from the URL, e.g. the part after `/docx/`)
  - Returns: document text content

- `feishu_list_doc_blocks` — List content blocks of a document (IDs, types, text preview)
  - Required: `document_id`
  - Optional: `page_size` (default 50)
  - Returns: block ID, type, and text preview for each block
  - Use this before `feishu_edit_doc` to discover block IDs

- `feishu_edit_doc` — Edit an existing Feishu document (append, update, or delete blocks)
  - Required: `document_id`, `action` (one of `append`, `update`, `delete`)
  - For `append`: provide `content` (each line becomes a text block); optional `parent_block_id` (defaults to document root), `index` (-1 for end)
  - For `update`: provide `block_id` and `content` (replaces the block's text)
  - For `delete`: provide `block_ids` (list of block IDs to remove)

#### Typical edit workflow

1. `feishu_read_doc` to see current content
2. `feishu_list_doc_blocks` to get block IDs
3. `feishu_edit_doc` with `action=update` to change a specific block, or `action=append` to add new content

### Spreadsheet Operations

- `feishu_create_sheet` — Create a new spreadsheet
  - Required: `title`
  - Optional: `folder_token`
  - Returns: spreadsheet URL and token

- `feishu_read_sheet` — Read data from a spreadsheet range
  - Required: `spreadsheet_token`, `range` (e.g. `Sheet1!A1:D10`)
  - Returns: cell values as tab-separated text

- `feishu_write_sheet` — Write data to a spreadsheet range
  - Required: `spreadsheet_token`, `range`, `values` (2D array)
  - Example: `values: [["Name", "Score"], ["Alice", "95"]]`

## Cross-Channel Usage

These tools work regardless of which channel the current conversation is on. You can create a Feishu doc from a Discord conversation, for example. Use the `message` tool to send the resulting document link to any channel.

## URL Patterns

- Documents: `https://xxx.feishu.cn/docx/{document_id}`
- Spreadsheets: `https://xxx.feishu.cn/sheets/{spreadsheet_token}`
