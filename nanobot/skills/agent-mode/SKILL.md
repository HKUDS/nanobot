---
name: agent-mode
description: Unified tool for managing agent LLM modes (add, remove, update, list, switch).
metadata: {"nanobot":{"emoji":"🔄"}}
---

# Agent Mode Manager

Unified tool for managing agent LLM modes including adding, removing, updating, listing, and switching models.

## Features

- List all available models with mode and description
- Switch to a specific model mode based on mode
- Add new model configurations
- Remove existing model configurations
- Update existing model configurations

## Tools

This skill provides the following tool:

### `agent_mode`

Unified tool for agent mode management.

**Parameters**:
- `method` (string, required): The method to perform - `add`, `remove`, `update`, `list`, or `switch`
- `mode` (string, optional): Mode name (e.g., "common", "coding", "multimodal"). Default is "common". Required for all methods except list.
- `model` (string, optional): Model identifier (e.g., "openai/qwen3.5:cloud"). Required for add and update methods.
- `describe` (string, optional): Description of the model. Required for add and update methods.

**Example - List all models**:
```
<tool>agent_mode</tool>
<parameter name="method">list</parameter>
```

**Example - Switch to coding mode**:
```
<tool>agent_mode</tool>
<parameter name="method">switch</parameter>
<parameter name="mode">coding</parameter>
```

**Example - Switch to common mode**:
```
<tool>agent_mode</tool>
<parameter name="method">switch</parameter>
<parameter name="mode">common</parameter>
```

**Example - Add a new coding model openai/qwen3-coder-next:cloud with describe: a coding model**:
```
<tool>agent_mode</tool>
<parameter name="method">add</parameter>
<parameter name="mode">coding</parameter>
<parameter name="model">openai/qwen3-coder-next:cloud</parameter>
<parameter name="describe">a coding model</parameter>
```

**Example - Remove the coding mode**:
```
<tool>agent_mode</tool>
<parameter name="method">remove</parameter>
<parameter name="mode">coding</parameter>
```

**Example - Update a model for coding to openai/qwen3-coder-next:cloud**:
```
<tool>agent_mode</tool>
<parameter name="method">update</parameter>
<parameter name="mode">coding</parameter>
<parameter name="model">openai/qwen3-coder-next:cloud</parameter>
```

## Usage

When users want to manage agent modes:

- "List all available models" → Call `agent_mode` with `method: "list"`
- "Switch to coding mode" → Call `agent_mode` with `method: "switch"`, `mode: "coding"`
- "Add a new model" → Call `agent_mode` with `method: "add"`, `mode: "xxx"`, `model: "xxx"`, `describe: "xxx"`
- "Remove a model" → Call `agent_mode` with `method: "remove"`, `mode: "xxx"`
- "Update a model" → Call `agent_mode` with `method: "update"`, `mode: "xxx"`, `model: "xxx"`, `describe: "xxx"`

Always use tool to manage agent modes, do not think by you self!
