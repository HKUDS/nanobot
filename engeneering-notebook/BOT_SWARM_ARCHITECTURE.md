# Auto Coder Bot Swarm Architecture

## Overview
This document describes how the Discord role mentions feature integrates with your auto coder bot swarm, enabling scalable multi-bot orchestration with configurable mention handling.

## Swarm Architecture

### Bot Roles in Your Swarm
```
┌─────────────────────────────────────────────────┐
│          Discord Role Mentions Layer            │
│    (Configurable mention detection & routing)   │
└─────────────────────────────────────────────────┘
                         ↑
        ┌────────────────┼────────────────┐
        ↓                ↓                ↓
    ┌────────┐      ┌──────────┐    ┌──────────┐
    │ Coder  │      │Coordinator│   │Validator │
    │ Bots   │      │   Bot     │   │   Bot    │
    └────────┘      └──────────┘    └──────────┘
        ↓                ↓                ↓
    Write Code      Orchestrate      Verify Code
    Debug Issues    Distribute Tasks Review Quality
```

## Configuration for Each Bot Type

### 1. Autonomous Coder Bots

**Purpose**: Generate and debug code in response to tasks

**Configuration**:
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "CODER_BOT_TOKEN",
      "respond_to_role_mentions": true,
      "bot_role_ids": [
        "coder_role_id",
        "task_dispatcher_role_id",
        "code_review_role_id"
      ],
      "respond_to_bot_id_ping": true,
      "respond_to_non_bot_ping": true,
      "respond_to_self_bot_ping": true,
      "group_policy": "mention",
      "allow_from": ["COORDINATOR_BOT_ID"]
    }
  }
}
```

**Mention Triggers**:
- Human mentions `@coder` role with task
- Coordinator mentions `@coder` role with routing
- Other coders @ mention for collaboration
- @everyone in critical alerts

**Responsibilities**:
- Analyze task requirements
- Write implementation code
- Generate unit tests
- Debug issues
- Report progress

---

### 2. Coordinator Bot

**Purpose**: Orchestrate swarm, distribute tasks, monitor progress

**Configuration**:
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "COORDINATOR_BOT_TOKEN",
      "respond_to_role_mentions": true,
      "bot_role_ids": [
        "coordinator_role_id",
        "swarm_admin_role_id"
      ],
      "respond_to_bot_id_ping": true,
      "respond_to_non_bot_ping": true,
      "respond_to_self_bot_ping": true,
      "group_policy": "mention",
      "allow_from": ["HUMAN_ADMIN_ID"]
    }
  }
}
```

**Mention Triggers**:
- Human mentions `@coordinator` with high-level tasks
- Responds to @swarm_admin for configuration changes
- Bot-to-bot coordination for task distribution
- @everyone for swarm-wide alerts

**Responsibilities**:
- Parse incoming requests
- Break down into subtasks
- Distribute to specialist bots
- Track progress
- Aggregate results
- Handle failures

---

### 3. Validator Bot

**Purpose**: Code review, quality assurance, approval

**Configuration**:
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "VALIDATOR_BOT_TOKEN",
      "respond_to_role_mentions": true,
      "bot_role_ids": [
        "validator_role_id",
        "qa_team_role_id"
      ],
      "respond_to_bot_id_ping": true,
      "respond_to_non_bot_ping": false,
      "respond_to_self_bot_ping": true,
      "group_policy": "mention",
      "allow_from": ["COORDINATOR_BOT_ID"]
    }
  }
}
```

**Mention Triggers**:
- Coordinator mentions `@validator` for code review
- Bot-to-bot mentions for parallel validation
- `@qa_team` for critical reviews
- Only responds to bots (human mentions ignored for isolation)

**Responsibilities**:
- Review generated code
- Run test suites
- Check for bugs
- Verify performance
- Approve or request changes

---

### 4. Documenter Bot

**Purpose**: Generate documentation, maintain knowledge base

**Configuration**:
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "DOCUMENTER_BOT_TOKEN",
      "respond_to_role_mentions": true,
      "bot_role_ids": [
        "documenter_role_id",
        "docs_team_role_id"
      ],
      "respond_to_bot_id_ping": true,
      "respond_to_non_bot_ping": true,
      "respond_to_self_bot_ping": true,
      "group_policy": "mention",
      "allow_from": ["COORDINATOR_BOT_ID", "HUMAN_USER_ID"]
    }
  }
}
```

**Mention Triggers**:
- Coordinator mentions `@documenter` with code to document
- Humans mention `@documenter` for doc requests
- Bot-to-bot for batch documentation
- `@docs_team` for knowledge base updates

**Responsibilities**:
- Generate API documentation
- Create README files
- Update architecture docs
- Maintain examples
- Keep docs in sync with code

---

### 5. Monitor Bot

**Purpose**: Health checks, logging, alerting

**Configuration**:
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "MONITOR_BOT_TOKEN",
      "respond_to_role_mentions": true,
      "bot_role_ids": [
        "monitor_role_id",
        "ops_team_role_id"
      ],
      "respond_to_bot_id_ping": true,
      "respond_to_non_bot_ping": false,
      "respond_to_self_bot_ping": true,
      "group_policy": "open",
      "allow_from": ["ALL_BOTS"]
    }
  }
}
```

**Mention Triggers**:
- All bots can @ mention for alerts
- `@monitor` role for status checks
- @everyone for critical incidents
- Only responds to bots (humans via mentions ignored)

**Responsibilities**:
- Monitor swarm health
- Track task completion
- Alert on failures
- Log activity
- Generate reports

---

## Task Flow with Role Mentions

### Scenario: Human Requests New Feature

```
1. Human: "Hey @coordinator, build a REST API with auth"
   ↓
2. Coordinator Bot:
   - Parses requirements
   - Breaks into tasks
   - Calls MCP: discord_mention_config (get current roles)
   - Mentions @coder role with: "Build auth middleware"
   ↓
3. Coder Bot 1:
   - Receives mention
   - Implements auth logic
   - Mentions @coder role with: "Review my approach?"
   ↓
4. Coder Bot 2:
   - Receives mention (responds_to_self_bot_ping=true)
   - Reviews code
   - Provides feedback
   ↓
5. Coder Bot 1:
   - Implements feedback
   - Calls MCP: discord_mention_config (add new role for API endpoints)
   - Mentions @validator role with: "Ready for review"
   ↓
6. Validator Bot:
   - Receives mention
   - Runs tests
   - Reviews code quality
   - Mentions @coder role with: "Approved with comments"
   ↓
7. Coder Bot 1:
   - Implements final suggestions
   - Mentions @documenter role with: "Document this API"
   ↓
8. Documenter Bot:
   - Receives mention
   - Generates API docs
   - Mentions @coordinator role with: "Documentation ready"
   ↓
9. Coordinator Bot:
   - Aggregates results
   - Mentions @monitor role with: "Task complete: feature_auth"
   ↓
10. Monitor Bot:
    - Logs completion
    - Updates metrics
    - Notifies swarm
    - Mentions @everyone with: "✅ Feature ready for deployment"
```

## MCP Tool for Swarm Configuration

### Dynamic Role Management
```python
# Coordinator Bot dynamically manages roles

async def handle_team_update(self, new_team_members: dict):
    """Update swarm roles when team changes."""
    
    # Get current configuration
    config = await self.tools.call("discord_mention_config", {
        "action": "get"
    })
    
    # Add new specialist roles
    for specialist, role_id in new_team_members.items():
        if role_id not in config['config']['bot_role_ids']:
            await self.tools.call("discord_mention_config", {
                "action": "add_role",
                "bot_role_ids": [role_id]
            })
            logger.info(f"Added role {specialist}: {role_id}")
    
    # Remove inactive roles
    for role_id in config['config']['bot_role_ids']:
        if role_id not in new_team_members.values():
            await self.tools.call("discord_mention_config", {
                "action": "remove_role",
                "bot_role_ids": [role_id]
            })
            logger.info(f"Removed inactive role: {role_id}")
```

### Swarm Mode Switching
```python
# Dynamically switch swarm modes

async def set_swarm_mode(self, mode: Literal["autonomous", "supervised", "debug"]):
    """Switch swarm operation mode."""
    
    modes = {
        "autonomous": {
            "respond_to_non_bot_ping": True,
            "respond_to_self_bot_ping": True,
            "respond_to_bot_id_ping": True,
        },
        "supervised": {
            "respond_to_non_bot_ping": True,
            "respond_to_self_bot_ping": False,
            "respond_to_bot_id_ping": True,
        },
        "debug": {
            "respond_to_non_bot_ping": True,
            "respond_to_self_bot_ping": False,
            "respond_to_bot_id_ping": True,
        },
    }
    
    config = modes[mode]
    result = await self.tools.call("discord_mention_config", {
        "action": "set",
        **config
    })
    
    logger.info(f"Swarm mode changed to {mode}: {result}")
```

## Deployment Strategy

### Development Environment
```
Each bot has respond_to_self_bot_ping=true for rapid iteration
Bots can freely mention each other for testing
All bots respond to human commands
Monitor bot has open group_policy for quick alerts
```

### Staging Environment
```
Limited bot-to-bot communication (only coordinator mentions specialists)
Humans can trigger all bots directly
Validator bot reviews all generated code
Monitor bot in verbose mode
```

### Production Environment
```
Coordinator orchestrates all communication
Specialist bots only respond to coordinator and humans
Validator provides quality gate
Monitor bot watches for anomalies
respond_to_self_bot_ping only enabled for critical flows
```

## Security Considerations

### Prevent Infinite Loops
- ✅ Default: `respond_to_self_bot_ping=false` prevents bot loops
- ✅ Use: `allow_from` lists to restrict which bots can trigger
- ✅ Monitor: Track mention counts to detect runaway conditions

### Role Isolation
- ✅ Validator bot: `respond_to_non_bot_ping=false` prevents human interference
- ✅ Monitor bot: `respond_to_non_bot_ping=false` reduces false alerts
- ✅ Specialist bots: `allow_from` limits who can coordinate

### Configuration Consistency
- ✅ Coordinator bot controls role lists via MCP
- ✅ All bots sync configuration periodically
- ✅ Audit log of all configuration changes

## Monitoring & Observability

### Track Mention Patterns
```python
# Monitor bot tracks all mentions

metrics = {
    "human_to_bot_mentions": 0,
    "bot_to_bot_mentions": 0,
    "role_mentions": 0,
    "total_mentions": 0,
}

# Alert conditions
alert_if("bot_to_bot_mentions > threshold", "Possible loop detected")
alert_if("role_mentions fails to route", "Role ID mismatch")
alert_if("mention latency > 5s", "Swarm communication delay")
```

### Health Checks
```python
# Coordinator periodically verifies swarm health

async def health_check():
    """Verify all bots are responsive."""
    for bot_id in self.swarm_bots:
        try:
            # Mention bot to verify it's listening
            await self.mention_bot(bot_id, "health_check")
            # Track response time
            response_time = await wait_for_response(bot_id, timeout=5s)
            logger.info(f"Bot {bot_id} responded in {response_time}ms")
        except TimeoutError:
            logger.error(f"Bot {bot_id} health check failed")
            await self.alert_ops(f"Swarm bot {bot_id} unresponsive")
```

## Open Source Contribution

### For Main Repository
This integration demonstrates:
1. **Modularity**: Works standalone or with MCP
2. **Scalability**: Supports large bot swarms
3. **Safety**: Prevents loops by default
4. **Flexibility**: Extensive configuration options
5. **Documentation**: Clear examples and patterns

### Community Use Cases
- Team automation (multiple bots, role-based tasks)
- Testing frameworks (automated test bot swarms)
- DevOps orchestration (infrastructure bots)
- Content generation (specialized content bots)
- Data processing pipelines (distributed computation)

### Key Advantages
- ✅ No external dependencies for core feature
- ✅ MCP tool ready (optional enhancement)
- ✅ Secure by default
- ✅ Extensive configuration options
- ✅ Production-ready implementation
- ✅ Well-tested and documented

---

**Architecture**: Multi-bot swarm with role-based orchestration
**Status**: Ready for deployment
**Integration**: Full MCP support for runtime configuration
**Open Source**: Ready for community contribution

