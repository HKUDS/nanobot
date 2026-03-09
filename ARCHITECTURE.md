# Nanobot Architecture

This document summarizes the runtime architecture implemented in the current repository.

## Basic Graph

```mermaid
flowchart LR
    User["User"]
    Channels["Input Channels\nTelegram / Discord / Slack / WhatsApp / Email / Matrix / CLI"]
    ChannelMgr["ChannelManager"]
    Bus["MessageBus\nInbound / Outbound queues"]
    Heartbeat["HeartbeatService\nreads HEARTBEAT.md"]
    Cron["CronService"]
    Agent["AgentLoop"]
    Context["ContextBuilder"]
    Session["SessionManager\nsessions/*.jsonl"]
    Memory["MemoryStore\nmemory/MEMORY.md\nmemory/PINNED.md\nmemory/HISTORY.md"]
    Skills["SkillsLoader\nworkspace skills + builtin skills"]
    Provider["LLM Provider"]
    Tools["ToolRegistry"]
    Web["Web tools\nweb_search / web_fetch"]
    MCP["MCP tools\nconnected external servers"]
    Local["Local tools\nfiles / shell / message / spawn / cron"]
    Subagents["SubagentManager"]

    User --> Channels
    Channels --> ChannelMgr
    ChannelMgr --> Bus
    Bus --> Agent
    Heartbeat --> Agent
    Cron --> Agent

    Agent --> Context
    Context --> Session
    Context --> Memory
    Context --> Skills

    Agent --> Provider
    Provider --> Agent

    Agent --> Tools
    Tools --> Web
    Tools --> MCP
    Tools --> Local
    Tools --> Subagents

    Agent --> Bus
    Bus --> ChannelMgr
    ChannelMgr --> Channels
    Channels --> User
```

## Styled Graph

```mermaid
flowchart TB
    classDef input fill:#FFF1C9,stroke:#9B6B00,color:#2B1C00,stroke-width:1px;
    classDef runtime fill:#DCEEFF,stroke:#185A9D,color:#0B2742,stroke-width:1px;
    classDef context fill:#E8F7E8,stroke:#2D7D46,color:#13361E,stroke-width:1px;
    classDef tools fill:#F7E3FF,stroke:#7A3AA1,color:#341047,stroke-width:1px;
    classDef external fill:#FFE2E2,stroke:#A13A3A,color:#4A1212,stroke-width:1px;

    subgraph Inputs["User Entry Points"]
        User["User"]:::input
        Telegram["Telegram Bot"]:::input
        OtherChannels["Other channels\nDiscord / Slack / WhatsApp / Email / Matrix / CLI"]:::input
    end

    subgraph Transport["Transport Layer"]
        ChannelMgr["ChannelManager"]:::runtime
        Bus["MessageBus\nconsume_inbound / publish_outbound"]:::runtime
    end

    subgraph Core["Agent Core"]
        Agent["AgentLoop\nprocess message\niterate tool calls\nreturn final response"]:::runtime
        Provider["LLM Provider"]:::external
    end

    subgraph PromptContext["Prompt + State"]
        Context["ContextBuilder"]:::context
        Session["SessionManager\nsession history"]:::context
        Memory["MemoryStore\nlong-term memory + pinned context + history"]:::context
        Skills["SkillsLoader\nbuiltin skills + workspace skills"]:::context
    end

    subgraph Tooling["Tool Execution"]
        Registry["ToolRegistry"]:::tools
        Web["WebSearchTool / WebFetchTool"]:::tools
        MCP["MCP wrappers\nmcp_<server>_<tool>"]:::tools
        Local["Read/Write/Edit/List\nExec\nMessage\nSpawn\nCron"]:::tools
        Subagents["SubagentManager"]:::tools
    end

    subgraph Automation["Automation"]
        Heartbeat["HeartbeatService\nLLM decides skip/run from HEARTBEAT.md"]:::runtime
        Cron["CronService\nscheduled jobs"]:::runtime
    end

    User --> Telegram
    User --> OtherChannels
    Telegram --> ChannelMgr
    OtherChannels --> ChannelMgr
    ChannelMgr --> Bus
    Bus --> Agent

    Heartbeat --> Agent
    Cron --> Agent

    Agent --> Context
    Context --> Session
    Context --> Memory
    Context --> Skills

    Agent --> Provider
    Provider --> Agent

    Agent --> Registry
    Registry --> Web
    Registry --> MCP
    Registry --> Local
    Registry --> Subagents

    Agent --> Bus
    Bus --> ChannelMgr
    ChannelMgr --> Telegram
    ChannelMgr --> OtherChannels
```

## Notes

- Input arrives through chat channels, then `ChannelManager` routes it onto the `MessageBus`.
- `AgentLoop` is the central orchestrator: it builds prompt context, calls the provider, executes tool calls, and publishes responses.
- Context is assembled from session history, workspace memory files, bootstrap files like `AGENTS.md`, and installed skills.
- Tooling is split between local tools, web tools, and dynamically connected MCP tools.
- Heartbeat and cron can trigger the same core agent loop without a human message.
