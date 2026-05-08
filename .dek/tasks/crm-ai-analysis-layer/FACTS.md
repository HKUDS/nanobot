# Facts

Task id: `crm-ai-analysis-layer`

User request: Build, on top of the current Nanobot Docker project, an AI analysis layer for a self-developed CRM. First version scope is read-only CRM access, CLI + DingTalk support, automated sales daily reports, automated sales weekly reports, cross-sales opportunity dashboard summaries, and delivery through the existing Docker approach. Current restrictions: skip Claude-Mem recall, do not write real CRM business data into `.dek` or long-term memory, do not read or request tokens/secrets/real customer data, and do not write business code now.

## Confirmed

1. The repository root contains `.dek/`, `.dockerignore`, `.env.nanobot`, `bridge/`, `docs/`, `entrypoint.sh`, `Dockerfile`, `docker-compose.yml`, `nanobot/`, `pyproject.toml`, `tests/`, and `webui/`.
   Evidence: directory listing of `/Users/yang/nanobot` returned these entries.

2. The only Docker/Compose files found by glob were `Dockerfile` and `docker-compose.yml`.
   Evidence: glob result for `**/{Dockerfile,docker-compose.yml,docker-compose.yaml,compose.yml,compose.yaml,*.Dockerfile}` returned `Dockerfile` and `docker-compose.yml`.

3. The Docker image uses base image `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`.
   Evidence: `Dockerfile:1`

4. The Dockerfile installs Node.js 20 dependencies plus `git`, `bubblewrap`, and `openssh-client`.
   Evidence: `Dockerfile:5-15`

5. The Dockerfile installs the Python package with `uv pip install --system --no-cache .`, first with a minimal copied package for dependency caching and then again after copying `nanobot/` and `bridge/`.
   Evidence: `Dockerfile:19-28`

6. The Dockerfile builds the WhatsApp bridge with `npm install && npm run build` under `/app/bridge`.
   Evidence: `Dockerfile:30-35`

7. The Dockerfile creates non-root user `nanobot` with UID `1000`, creates `/home/nanobot/.nanobot`, sets `HOME=/home/nanobot`, exposes port `18790`, uses `entrypoint.sh`, and defaults to command `status`.
   Evidence: `Dockerfile:37-52`

8. `entrypoint.sh` checks whether `$HOME/.nanobot` is writable and exits with ownership-fix guidance if not.
   Evidence: `entrypoint.sh:1-14`

9. `entrypoint.sh` ultimately executes the CLI with `exec nanobot "$@"`.
   Evidence: `entrypoint.sh:15`

10. `docker-compose.yml` defines a shared `x-common-config` that builds from the local Dockerfile, mounts `~/.nanobot:/home/nanobot/.nanobot`, uses `.env.nanobot` as `env_file`, drops all capabilities, adds `SYS_ADMIN`, and disables AppArmor/seccomp confinement.
    Evidence: `docker-compose.yml:1-15`

11. `docker-compose.yml` defines `nanobot-gateway` with command `gateway`, restart policy `unless-stopped`, and port mapping `18790:18790`.
    Evidence: `docker-compose.yml:17-32`

12. `docker-compose.yml` defines `nanobot-api` with command `serve --host 0.0.0.0 -w /home/nanobot/.nanobot/api-workspace` and port mapping `127.0.0.1:8900:8900`.
    Evidence: `docker-compose.yml:34-49`

13. `docker-compose.yml` defines `nanobot-cli` under profile `cli`, with command `status`, `stdin_open: true`, and `tty: true`.
    Evidence: `docker-compose.yml:51-57`

14. Deployment docs show Docker Compose onboarding, config edit, gateway start, CLI agent run, log follow, and shutdown commands.
    Evidence: `docs/deployment.md:13-25`

15. Deployment docs show non-compose Docker commands for build, onboard, gateway, agent, and status.
    Evidence: `docs/deployment.md:27-45`

16. Docker deployment docs say config should be mounted at `/home/nanobot/.nanobot`, the container runs as non-root UID `1000`, and official Docker usage means building from this repository's included Dockerfile.
    Evidence: `docs/deployment.md:3-12`

17. `.dockerignore` excludes `.env`, `.git`, `node_modules/`, `bridge/dist/`, and `workspace/`, but does not list `.env.nanobot`.
    Evidence: `.dockerignore:1-13`

18. The Python package is named `nanobot-ai`, requires Python `>=3.11`, and describes itself as a lightweight personal AI assistant framework.
    Evidence: `pyproject.toml:1-7`

19. Core runtime dependencies include `dingtalk-stream`, `httpx`, `mcp`, `jinja2`, `openai`, `anthropic`, and other channel/tool dependencies.
    Evidence: `pyproject.toml:25-65`

20. Development dependencies include `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, and `pymupdf`.
    Evidence: `pyproject.toml:100-107`

21. The Python CLI entry point exists as `nanobot = "nanobot.cli.commands:app"`.
    Evidence: `pyproject.toml:109-110`

22. The Typer app is named `nanobot`.
    Evidence: `nanobot/cli/commands.py:74-79`

23. Top-level CLI commands are implemented for `onboard`, `serve`, `gateway`, `agent`, and `status`.
    Evidence: grep result for `def (onboard|serve|gateway|agent|status)` in `nanobot/cli/commands.py` returned lines 305, 515, 609, 1033, and 1476.

24. CLI docs list `nanobot onboard`, `nanobot agent`, `nanobot serve`, `nanobot gateway`, `nanobot status`, provider login, and channel login/status commands.
    Evidence: `docs/cli-reference.md:3-21`

25. The `agent` CLI command accepts `--message/-m`, `--session/-s`, `--workspace/-w`, `--config/-c`, `--markdown/--no-markdown`, and `--logs/--no-logs` options.
    Evidence: `nanobot/cli/commands.py:1032-1041`

26. The `agent` CLI command creates `MessageBus`, provider, `CronService`, and `AgentLoop`, passing config for workspace, tools, MCP servers, channels, timezone, unified session, disabled skills, session TTL, and memory/message limits.
    Evidence: `nanobot/cli/commands.py:1048-1091`

27. The documented Python development commands are `pip install -e ".[dev]"`, `pytest`, `ruff check nanobot/`, and `ruff format nanobot/`.
    Evidence: `CONTRIBUTING.md:88-108`

28. Pytest is configured with `asyncio_mode = "auto"` and `testpaths = ["tests"]`.
    Evidence: `pyproject.toml:154-156`

29. WebUI scripts include `dev`, `build`, `preview`, `test` as `vitest run`, `test:watch`, and `lint` as `eslint src --max-warnings 0`.
    Evidence: `webui/package.json:6-13`

30. Bridge scripts include `build` as `tsc`, `start` as `node dist/index.js`, and `dev` as `tsc && node dist/index.js`; no bridge test script is defined.
    Evidence: `bridge/package.json:7-10`

31. Built-in channels are discovered by scanning `nanobot.channels`, while external channel plugins are discovered through the `nanobot.channels` entry point group; built-ins take priority over plugins with the same name.
    Evidence: `nanobot/channels/registry.py:17-25`, `nanobot/channels/registry.py:40-51`, `nanobot/channels/registry.py:54-71`

32. `BaseChannel` defines the channel integration interface with abstract `start`, `stop`, and `send`, optional streaming via `send_delta`, allow-list checks, and `_handle_message` for publishing inbound messages to the bus.
    Evidence: `nanobot/channels/base.py:15-31`, `nanobot/channels/base.py:81-128`, `nanobot/channels/base.py:130-190`

33. Channel configs can accept extra fields because `ChannelsConfig` sets `extra="allow"`.
    Evidence: `nanobot/config/schema.py:18-32`

34. `ChannelManager` initializes discovered enabled channels from config, applies transcription/progress/tool-hint settings, and validates non-empty allow lists.
    Evidence: `nanobot/channels/manager.py:67-112`

35. DingTalk support exists as a built-in channel implemented with DingTalk Stream mode.
    Evidence: `nanobot/channels/dingtalk.py:1-22`, `nanobot/channels/dingtalk.py:165-174`

36. `DingTalkConfig` has `enabled`, `client_id`, `client_secret`, `allow_from`, `allow_remote_media_redirects`, and `remote_media_redirect_allowed_hosts` fields.
    Evidence: `nanobot/channels/dingtalk.py:154-163`

37. DingTalk channel startup requires `dingtalk-stream` availability and configured `client_id`/`client_secret`, then creates a `DingTalkStreamClient` and registers a `ChatbotMessage` handler.
    Evidence: `nanobot/channels/dingtalk.py:202-239`

38. DingTalk outbound sending supports private and group routes; group chat IDs use the `group:` prefix and send to `https://api.dingtalk.com/v1.0/robot/groupMessages/send`.
    Evidence: `nanobot/channels/dingtalk.py:535-565`

39. DingTalk inbound `_on_message` maps group conversations to `chat_id = "group:<conversation_id>"` and publishes messages with metadata including sender name, platform, and conversation type.
    Evidence: `nanobot/channels/dingtalk.py:679-705`

40. Tests cover DingTalk group routing and group send API behavior.
    Evidence: `tests/channels/test_dingtalk_channel.py:81-119`

41. Chat app docs list DingTalk as a supported channel requiring App Key + App Secret.
    Evidence: `docs/chat-apps.md:5-19`

42. Tools are dynamically managed by `ToolRegistry`, which supports register/unregister/get/definition generation and execution after schema validation.
    Evidence: `nanobot/agent/tools/registry.py:8-23`, `nanobot/agent/tools/registry.py:48-71`, `nanobot/agent/tools/registry.py:73-114`

43. Tool implementations subclass `Tool`, expose `name`, `description`, `parameters`, and `execute`, and can mark themselves `read_only` and `concurrency_safe`.
    Evidence: `nanobot/agent/tools/base.py:117-172`

44. `AgentLoop._register_default_tools` registers ask-user, file read/write/edit/list, glob/grep, notebook edit, optional exec, optional web search/fetch, message, spawn, and cron tools.
    Evidence: `nanobot/agent/loop.py:360-412`

45. MCP servers are configured under `tools.mcp_servers`; MCP config includes stdio/HTTP transport fields, headers, per-tool timeout, and `enabled_tools` defaulting to `[*]`.
    Evidence: `nanobot/config/schema.py:237-248`, `nanobot/config/schema.py:256-264`

46. Nanobot connects configured MCP servers lazily from `AgentLoop._connect_mcp`.
    Evidence: `nanobot/agent/loop.py:414-434`

47. MCP connection supports stdio, SSE, and streamable HTTP transports; it registers tools and can filter them by `enabledTools`.
    Evidence: `nanobot/agent/tools/mcp.py:433-540`

48. MCP connection also attempts to register MCP resources and prompts as wrapped Nanobot tools.
    Evidence: `nanobot/agent/tools/mcp.py:560-584`

49. Configuration docs describe MCP as a way to connect external tool servers and use them as native agent tools, with support for stdio and HTTP transports and `enabledTools` filtering.
    Evidence: `docs/configuration.md:918-990`

50. Skills are markdown files named `SKILL.md`; workspace skills live under `<workspace>/skills`, built-in skills under `nanobot/skills`, and workspace skills shadow built-ins by name.
    Evidence: `nanobot/agent/skills.py:21-33`, `nanobot/agent/skills.py:35-73`

51. `SkillsLoader` can load a skill, build a skills summary, filter unavailable skills based on required binaries/env vars, and load always-on skills.
    Evidence: `nanobot/agent/skills.py:75-142`, `nanobot/agent/skills.py:189-213`

52. Built-in skills currently found include weather, tmux, update-setup, summarize, cron, my, github, skill-creator, memory, and clawhub.
    Evidence: glob result for `nanobot/skills/*/SKILL.md`

53. `ContextBuilder` assembles the system prompt from identity, workspace bootstrap files, memory, always-on skills, skill summary, and recent unprocessed history.
    Evidence: `nanobot/agent/context.py:17-67`

54. Workspace bootstrap files considered by `ContextBuilder` are `AGENTS.md`, `SOUL.md`, `USER.md`, and `TOOLS.md`.
    Evidence: `nanobot/agent/context.py:20`, `nanobot/agent/context.py:112-120`

55. Memory files are managed under the workspace by `MemoryStore`, including `memory/MEMORY.md`, `memory/history.jsonl`, `SOUL.md`, `USER.md`, cursor files, and a `GitStore` for selected durable memory files.
    Evidence: `nanobot/agent/memory.py:39-65`

56. Memory docs describe `session.messages` as short-term conversation, `memory/history.jsonl` as running archive, and `SOUL.md`, `USER.md`, and `memory/MEMORY.md` as durable knowledge files.
    Evidence: `docs/memory.md:9-20`

57. Dream reads new `memory/history.jsonl` entries and existing long-term files, then edits durable memory files; Dream configuration lives under `agents.defaults.dream`.
    Evidence: `docs/memory.md:46-63`, `docs/memory.md:141-172`

58. Dream's editing tool registry can read within the workspace, edit within the workspace, and write only under `skills/`.
    Evidence: `nanobot/agent/memory.py:706-778`

59. The gateway registers Dream as an internal system cron job and starts cron and heartbeat services when the gateway runs.
    Evidence: `nanobot/cli/commands.py:953-967`, `nanobot/cli/commands.py:992-1003`

60. `CronTool` supports `add`, `list`, and `remove` actions and can schedule by interval, cron expression, or one-time ISO datetime.
    Evidence: `nanobot/agent/tools/cron.py:17-51`, `nanobot/agent/tools/cron.py:126-190`

61. `CronService.add_job` creates agent-turn jobs with payload fields for message, delivery flag, channel, destination, channel metadata, and session key.
    Evidence: `nanobot/cron/service.py:476-520`

62. Heartbeat reads `<workspace>/HEARTBEAT.md`, asks the model to choose `skip` or `run`, executes active tasks through a callback, and optionally notifies the last active channel.
    Evidence: `nanobot/heartbeat/service.py:40-51`, `nanobot/heartbeat/service.py:75-87`, `nanobot/heartbeat/service.py:184-236`

63. Chat command docs say the gateway wakes every 30 minutes, checks `HEARTBEAT.md`, and delivers results to the most recently active chat channel if tasks are present.
    Evidence: `docs/chat-commands.md:18-33`

64. Providers are registry-driven; comments say adding a provider requires adding a `ProviderSpec` and a `ProvidersConfig` field.
    Evidence: `nanobot/providers/registry.py:1-11`, `nanobot/providers/registry.py:21-88`

65. Provider factory dispatch supports Azure OpenAI, OpenAI Codex, GitHub Copilot, Anthropic, Bedrock, and OpenAI-compatible providers.
    Evidence: `nanobot/providers/factory.py:21-92`

66. Runtime config root contains `agents`, `channels`, `providers`, `api`, `gateway`, and `tools`, and supports environment variables with prefix `NANOBOT_` and nested delimiter `__`.
    Evidence: `nanobot/config/schema.py:267-275`, `nanobot/config/schema.py:375`

67. Security docs recommend production settings `"restrictToWorkspace": true` and `"tools.exec.sandbox": "bwrap"`, document that empty `allowFrom` denies all, and state the official Docker image runs as non-root UID 1000 with bubblewrap pre-installed.
    Evidence: `docs/configuration.md:995-1009`

68. Content search for `CRM|crm|商机|日报|周报|看板` found only Feishu test fixture text for `日报`, and no CRM/opportunity/dashboard implementation files.
    Evidence: grep result for that pattern under `/Users/yang/nanobot` returned only `tests/channels/test_feishu_post_content.py:19` and `tests/channels/test_feishu_post_content.py:32`.

69. Claude-Mem recall was intentionally skipped for this task because the user explicitly stated Claude-Mem is not installed and requested skipping recall.
    Evidence: direct user request in this task.

70. No token, secret, real CRM customer data, or `.env*` contents were read for this task.
    Evidence: task execution constraint; `.env.nanobot` was listed but not read.

71. The `nanobot/` package currently has top-level subpackages for `agent`, `api`, `bus`, `channels`, `cli`, `command`, `config`, `cron`, `heartbeat`, `providers`, `security`, `session`, `skills`, `templates`, `utils`, and `web`.
    Evidence: directory listing of `nanobot/`.

72. Existing built-in agent tools are organized as one module per tool or tool family under `nanobot/agent/tools/`, including `cron.py`, `filesystem.py`, `mcp.py`, `message.py`, `search.py`, `shell.py`, and `web.py`.
    Evidence: directory listing of `nanobot/agent/tools/`.

73. The `nanobot/cli/` package currently contains `commands.py`, `models.py`, `onboard.py`, and `stream.py`; the Typer app and top-level command implementations live in `commands.py`.
    Evidence: directory listing of `nanobot/cli/`, `nanobot/cli/commands.py:74-79`, `nanobot/cli/commands.py:1032-1041`

74. Slash/in-chat command infrastructure is separated from CLI command definitions under `nanobot/command/`, with `router.py` providing `CommandRouter` and `builtin.py` registering default slash commands.
    Evidence: directory listing of `nanobot/command/`, `nanobot/command/router.py:1-12`, `nanobot/command/router.py:27-98`, `nanobot/command/builtin.py:473-487`

75. `AgentLoop` imports `CommandContext`, `CommandRouter`, and `register_builtin_commands`, constructs a command router, and registers built-in slash commands during initialization.
    Evidence: `nanobot/agent/loop.py:40-44`, `nanobot/agent/loop.py:318-324`

76. Existing channel implementations are organized as one module per channel under `nanobot/channels/`, including `dingtalk.py`, `feishu.py`, `telegram.py`, `slack.py`, `websocket.py`, and others.
    Evidence: directory listing of `nanobot/channels/`.

77. External channel plugins can live outside the `nanobot/` package and register under the `nanobot.channels` entry point group; the guide's example package is `nanobot-channel-webhook/` with implementation under `nanobot_channel_webhook/`.
    Evidence: `docs/channel-plugin-guide.md:7-15`, `docs/channel-plugin-guide.md:20-28`, `docs/channel-plugin-guide.md:131-151`

78. The current package build includes `nanobot/**/*.py`, `nanobot/templates/**/*.md`, `nanobot/skills/**/*.md`, and `nanobot/skills/**/*.sh`, and the wheel package root is `nanobot`.
    Evidence: `pyproject.toml:119-131`

79. Python tests are grouped under domain directories matching runtime packages, including `tests/agent`, `tests/channels`, `tests/cli`, `tests/command`, `tests/config`, `tests/cron`, `tests/heartbeat`, `tests/providers`, `tests/security`, `tests/session`, `tests/tools`, and `tests/utils`.
    Evidence: directory listing of `tests/`.

80. `MessageTool` is the existing generic path for sending messages to user channels, accepts optional `channel` and `chat_id`, and publishes `OutboundMessage` through its configured callback.
    Evidence: `nanobot/agent/tools/message.py:14-31`, `nanobot/agent/tools/message.py:109-181`

81. `DingTalkChannel.send` already sends outbound `OutboundMessage` content and media to DingTalk, while `_on_message` handles inbound DingTalk messages and delegates to `BaseChannel._handle_message`.
    Evidence: `nanobot/channels/dingtalk.py:657-705`

82. MCP tools are wrapped as `MCPToolWrapper` instances in `nanobot/agent/tools/mcp.py`, with generated names prefixed by `mcp_<server>_<tool>`.
    Evidence: `nanobot/agent/tools/mcp.py:144-168`, `nanobot/agent/tools/mcp.py:433-540`

83. Agent turn persistence happens in `AgentLoop._save_turn`, which saves new assistant/tool/user messages into session history and truncates large tool results.
    Evidence: `nanobot/agent/loop.py:1144-1152`, `nanobot/agent/loop.py:1222-1259`

84. The provided CRM GraphQL schema documents the endpoint as `http://api.in.chaitin.net/crm/query`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:10`

85. The provided CRM GraphQL schema has root `Query`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:13-19`

86. The provided CRM GraphQL schema has root `Mutation`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:13-17`, `/Users/yang/Desktop/CRM_schema.md:498`

87. The v1-relevant query `listUser` exists as `listUser(search: UserSearchParam!, pagination: PaginationParam): UserConnection!`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:42`

88. The v1-relevant query `listReport` exists as `listReport(search: [ReportSearchParam!], pagination: PaginationParam): ReportConnection!`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:44`

89. The v1-relevant query `listCompany` exists as `listCompany(search: [CompanySearchParam!], pagination: PaginationParam): CompanyConnection!`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:78`

90. The v1-relevant query `companyInfo` exists as `companyInfo(id: ID!): Company!`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:91`

91. The v1-relevant query `listProject` exists as `listProject(search: ProjectSearchParam!, pagination: PaginationParam, sort_by: SortBy! = {by:"updatedAt",order:-1}): ProjectConnection!`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:105`

92. The v1-relevant query `projectInfo` exists as `projectInfo(id: ID!): Project!`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:127`

93. The v1-relevant query `reportInfo` exists as `reportInfo(id: ID!): Report`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:165`

94. The v1-relevant query `listActivity` exists as `listActivity(search: [ActivitySearchParam!], pagination: PaginationParam): ActivityConnection!`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:169`

95. The v1-relevant query `reportRelatedInfo` exists as `reportRelatedInfo(target: Time!, creator: ID!, type: ReportType!): ReportRelatedInfo!`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:175`

96. The v1-relevant query `list_business_chance` exists as `list_business_chance(search: BusinessChanceSearchParam, pagination: PaginationParam): BusinessChanceConnection!`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:213`

97. The v1-relevant query `business_chance` exists as `business_chance(id: ID!): BusinessChance`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:215`

98. The CRM schema includes many mutation fields under `Mutation`, including update/create/cancel/add/sync/audit/review/remove-style operations, so v1 must explicitly prohibit all Mutation usage.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:498-617`

99. The CRM schema defines connection pagination objects using `total`, `skip`, `limit`, and `data`, and defines `PaginationParam` with `skip` and `limit`.
    Evidence: `/Users/yang/Desktop/CRM_schema.md:8004-8011`, `/Users/yang/Desktop/CRM_schema.md:8170-8177`, `/Users/yang/Desktop/CRM_schema.md:8645-8652`, `/Users/yang/Desktop/CRM_schema.md:13445-13452`, `/Users/yang/Desktop/CRM_schema.md:7552-7558`

100. The CRM schema defines relevant search input fields for `ActivitySearchParam`, `BusinessChanceSearchParam`, `CompanySearchParam`, `ProjectSearchParam`, `ReportSearchParam`, and `UserSearchParam`.
     Evidence: `/Users/yang/Desktop/CRM_schema.md:5351-5363`, `/Users/yang/Desktop/CRM_schema.md:5371-5385`, `/Users/yang/Desktop/CRM_schema.md:5445-5472`, `/Users/yang/Desktop/CRM_schema.md:7638-7687`, `/Users/yang/Desktop/CRM_schema.md:7715-7723`, `/Users/yang/Desktop/CRM_schema.md:7951-7959`

101. Task 14A is documentation-only: no real CRM endpoint was accessed, `.env.nanobot` was not read, no token/secret was requested or output, no RealCRMAdapter was implemented, and no DingTalk integration was changed.
     Evidence: direct user request for 14A and this task execution scope.

## Open Questions

1. What authentication mechanism should the GraphQL endpoint use at runtime: bearer token, cookie, internal gateway header, mTLS, or another mechanism?

2. Which project date field defines inclusion in daily and weekly pipeline metrics: `updated_at`, `created_at`, `deal_date`, `sign_date`, or `estimated_deal_date`?

3. Which owner field is authoritative for sales scope: `sales`, `claim_by`, `claimBy.user.id`, `claim_by_group`, or another field?

4. What is the exact JSON shape of the `Money` scalar in real GraphQL responses?

5. Should `BusinessChance` be merged into the same normalized opportunity stream as `Project`, or reported as a separate source category?

6. Which free-text fields, if any, are allowed in AI-readable summaries after redaction?

7. What page size and rate limits are safe for production CRM reads?

8. Should optional real CRM smoke tests run only behind an explicit environment flag and never in default CI?

9. What DingTalk delivery targets are required later: one-to-one users, one or more group conversations, or both?

10. Should CRM analysis outputs be excluded from Nanobot long-term memory and Dream entirely, or only raw CRM/source data?
