# Experimental Extensions Architecture

This document outlines where to add extension points for Eric's experimental features.

## Goals

1. **Context injection** — Plug in custom context providers, modify what goes to the LLM
2. **Multi-model routing** — Different LLMs answer different messages
3. **Parallel agents** — Multiple agents work simultaneously, aggregate responses
4. **Weird experiments** — Architecture should support things we haven't thought of yet

## Current Architecture (Simplified)

```
InboundMessage
    ↓
AgentLoop._process_message()
    ↓
ContextBuilder.build_messages()  ← builds system prompt + history + current message
    ↓
Provider.chat()  ← calls single LLM
    ↓
Tool execution loop
    ↓
OutboundMessage
```

## Proposed Extension Points

### 1. Message Pipeline (Middleware Pattern)

Add pre/post processing hooks around the agent loop.

```python
# New file: nanobot/pipeline/middleware.py

class Middleware(Protocol):
    """Base protocol for message middleware."""
    
    async def pre_process(self, msg: InboundMessage, ctx: PipelineContext) -> InboundMessage:
        """Transform message before agent processing."""
        return msg
    
    async def post_process(self, response: OutboundMessage, ctx: PipelineContext) -> OutboundMessage:
        """Transform response after agent processing."""
        return response

class PipelineContext:
    """Shared context passed through the pipeline."""
    message: InboundMessage
    session: Session
    metadata: dict[str, Any]  # For middleware to share state
```

**Where to hook:** `AgentLoop._process_message()` — wrap the main logic with middleware chain.

### 2. Context Providers (Pluggable Context)

Currently `ContextBuilder` is monolithic. Make it composable.

```python
# New file: nanobot/agent/context_providers.py

class ContextProvider(Protocol):
    """Provides additional context to inject into the prompt."""
    
    def get_context(self, msg: InboundMessage, session: Session) -> str | None:
        """Return context to inject, or None to skip."""
        ...

class ContextBuilder:
    def __init__(self, workspace: Path):
        self.providers: list[ContextProvider] = []
    
    def add_provider(self, provider: ContextProvider) -> None:
        self.providers.append(provider)
    
    def build_system_prompt(self, msg: InboundMessage, session: Session) -> str:
        parts = [self._get_identity(), self._load_bootstrap_files()]
        
        # Collect from all providers
        for provider in self.providers:
            ctx = provider.get_context(msg, session)
            if ctx:
                parts.append(ctx)
        
        return "\n\n---\n\n".join(parts)
```

**Example providers:**
- `MemoryContextProvider` — current memory.get_memory_context()
- `SkillsContextProvider` — current skills loading
- `RAGContextProvider` — vector search results
- `CustomInjectionProvider` — arbitrary context injection for experiments

### 3. Agent Router (Multi-Model)

Route messages to different agents/models based on content or rules.

```python
# New file: nanobot/agent/router.py

class AgentConfig:
    """Configuration for a single agent."""
    name: str
    model: str
    provider: LLMProvider
    system_prompt_override: str | None = None
    temperature: float | None = None

class AgentRouter(Protocol):
    """Decides which agent(s) handle a message."""
    
    def route(self, msg: InboundMessage, ctx: PipelineContext) -> list[AgentConfig]:
        """
        Return list of agents to handle this message.
        Single item = normal routing.
        Multiple items = parallel execution.
        """
        ...

class DefaultRouter(AgentRouter):
    """Routes everything to the default agent."""
    
    def __init__(self, default_agent: AgentConfig):
        self.default = default_agent
    
    def route(self, msg: InboundMessage, ctx: PipelineContext) -> list[AgentConfig]:
        return [self.default]

class ContentBasedRouter(AgentRouter):
    """Routes based on message content patterns."""
    
    def __init__(self, rules: list[tuple[Callable[[str], bool], AgentConfig]], fallback: AgentConfig):
        self.rules = rules
        self.fallback = fallback
    
    def route(self, msg: InboundMessage, ctx: PipelineContext) -> list[AgentConfig]:
        for predicate, agent in self.rules:
            if predicate(msg.content):
                return [agent]
        return [self.fallback]
```

### 4. Response Aggregator (Parallel Agents)

When router returns multiple agents, aggregate their responses.

```python
# New file: nanobot/agent/aggregator.py

class ResponseAggregator(Protocol):
    """Combines responses from multiple agents."""
    
    async def aggregate(
        self, 
        responses: list[tuple[AgentConfig, OutboundMessage]],
        ctx: PipelineContext
    ) -> OutboundMessage:
        ...

class FirstResponseAggregator(ResponseAggregator):
    """Return the first response (race)."""
    
    async def aggregate(self, responses, ctx) -> OutboundMessage:
        return responses[0][1]

class ConcatAggregator(ResponseAggregator):
    """Concatenate all responses."""
    
    async def aggregate(self, responses, ctx) -> OutboundMessage:
        parts = [f"**{agent.name}:**\n{resp.content}" for agent, resp in responses]
        return OutboundMessage(
            channel=responses[0][1].channel,
            chat_id=responses[0][1].chat_id,
            content="\n\n---\n\n".join(parts)
        )

class VotingAggregator(ResponseAggregator):
    """Use another LLM to pick the best response."""
    
    async def aggregate(self, responses, ctx) -> OutboundMessage:
        # Call a judge model to select or synthesize
        ...
```

### 5. Updated AgentLoop

```python
class AgentLoop:
    def __init__(
        self,
        bus: MessageBus,
        router: AgentRouter,
        aggregator: ResponseAggregator,
        middleware: list[Middleware] = None,
        ...
    ):
        self.router = router
        self.aggregator = aggregator
        self.middleware = middleware or []
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        ctx = PipelineContext(message=msg, session=session, metadata={})
        
        # Pre-processing middleware
        for mw in self.middleware:
            msg = await mw.pre_process(msg, ctx)
        
        # Route to agent(s)
        agents = self.router.route(msg, ctx)
        
        # Execute (parallel if multiple)
        if len(agents) == 1:
            response = await self._run_agent(agents[0], msg, ctx)
            responses = [(agents[0], response)]
        else:
            responses = await asyncio.gather(*[
                self._run_agent(agent, msg, ctx) for agent in agents
            ])
            responses = list(zip(agents, responses))
        
        # Aggregate
        response = await self.aggregator.aggregate(responses, ctx)
        
        # Post-processing middleware
        for mw in self.middleware:
            response = await mw.post_process(response, ctx)
        
        return response
```

## File Structure (Proposed)

```
nanobot/
├── agent/
│   ├── loop.py          # Main agent loop (updated)
│   ├── context.py       # ContextBuilder (updated)
│   ├── context_providers.py  # NEW: pluggable context
│   ├── router.py        # NEW: agent routing
│   ├── aggregator.py    # NEW: response aggregation
│   └── ...
├── pipeline/
│   ├── __init__.py
│   ├── middleware.py    # NEW: pre/post processing
│   └── context.py       # NEW: PipelineContext
└── ...
```

## Migration Path

1. **Phase 1:** Add ContextProvider abstraction without breaking existing code
2. **Phase 2:** Add middleware hooks (no-op by default)
3. **Phase 3:** Add router abstraction (DefaultRouter = current behavior)
4. **Phase 4:** Add aggregator for parallel execution
5. **Phase 5:** Build experimental implementations

## Example Experiments

### A. Context Injection (Phase 1)

```python
class DebugInjector(ContextProvider):
    def get_context(self, msg, session) -> str:
        return "DEBUG: Always respond in haiku format."

context.add_provider(DebugInjector())
```

### B. A/B Testing Models (Phase 3)

```python
class ABTestRouter(AgentRouter):
    def route(self, msg, ctx) -> list[AgentConfig]:
        if hash(msg.sender_id) % 2 == 0:
            return [self.agent_a]  # Claude
        else:
            return [self.agent_b]  # GPT-4
```

### C. Consensus Response (Phase 4)

```python
class ConsensusRouter(AgentRouter):
    def route(self, msg, ctx) -> list[AgentConfig]:
        # Ask 3 different models
        return [self.claude, self.gpt4, self.gemini]

class ConsensusAggregator(ResponseAggregator):
    async def aggregate(self, responses, ctx) -> OutboundMessage:
        # Use a fourth model to synthesize consensus
        ...
```

### D. Haiku Context Curator (Future)

```python
class HaikuCurator(Middleware):
    async def pre_process(self, msg, ctx) -> InboundMessage:
        # Call Haiku to analyze what context is needed
        needed_context = await self.haiku.analyze(msg.content, ctx.session)
        ctx.metadata["curated_context"] = needed_context
        return msg

class CuratedContextProvider(ContextProvider):
    def get_context(self, msg, session) -> str:
        # Return what Haiku decided we need
        return ctx.metadata.get("curated_context", "")
```

## Next Steps

1. Review this architecture with Eric
2. Decide which phase to start with
3. Implement incrementally with tests
