# nanobot-turbo Implementation Plan

## Project Overview
**Repository**: https://github.com/jhonny-cinco-ai/nanobot-turbo  
**Branch**: feature/smart-router  
**Status**: Core routing system implemented ✅

## Smart Router Architecture

### Completed ✅

#### 1. Core Router Components (`nanobot/agent/router/`)
- **`models.py`** - Data models for routing decisions
  - `RoutingTier` enum (SIMPLE, MEDIUM, COMPLEX, REASONING)
  - `RoutingDecision` dataclass
  - `ClassificationScores` (14-dimension system)
  - `RoutingPattern` for learned patterns

- **`classifier.py`** - Client-side Layer 1 classification
  - 14-dimension weighted scoring
  - Sigmoid confidence calibration
  - Pattern matching with regex
  - Token estimation
  - Tool requirement detection

- **`llm_router.py`** - LLM-assisted Layer 2 fallback
  - GPT-4o-mini classification
  - JSON response parsing
  - 500ms timeout
  - Error fallback to MEDIUM tier

- **`sticky.py`** - Sticky routing logic
  - Maintains tier across conversation
  - Context window (5 messages)
  - Smart downgrade detection
  - Per-message override capability

- **`calibration.py`** - Auto-calibration system
  - Learns from Layer 1 vs Layer 2 comparisons
  - Pattern generation from mismatches
  - Periodic calibration (default: 24h)
  - Pattern eviction for low-success patterns

#### 2. Pipeline Integration (`nanobot/agent/stages/`)
- **`routing_stage.py`** - Context pipeline stage
  - `RoutingContext` for state management
  - `RoutingStage` for pipeline integration
  - Fire-and-forget analytics
  - Calibration trigger

#### 3. Configuration (`nanobot/config/schema.py`)
- Added `RoutingConfig` with full schema
- Tier configuration (simple/medium/complex/reasoning)
- Client classifier settings
- LLM classifier settings
- Sticky routing settings
- Auto-calibration settings

#### 4. Example Configuration
- **`config.example.json`** - Complete example with all routing options

## Next Steps

### Priority 1: Integration ⚡
- [ ] **Integrate RoutingStage into AgentLoop**
  - Modify `nanobot/agent/loop.py`
  - Replace static model selection with smart routing
  - Add routing context to message processing
  - Test with various message types

- [ ] **Update AgentLoop initialization**
  - Pass routing config to AgentLoop
  - Initialize RoutingStage with provider
  - Wire up analytics/logging

### Priority 2: CLI Commands 🖥️
- [ ] **Add `nanobot routing` commands**
  ```bash
  nanobot routing status       # Show current routing config and stats
  nanobot routing calibrate    # Manually trigger calibration
  nanobot routing patterns     # List learned patterns
  nanobot routing test "msg"   # Test classification on a message
  nanobot routing analytics    # Show cost savings and routing stats
  ```

- [ ] **Update CLI help and documentation**

### Priority 3: Testing 🧪
- [ ] **Unit tests for classifier**
  - Test 14-dimension scoring
  - Test pattern matching
  - Test confidence calibration
  
- [ ] **Unit tests for sticky routing**
  - Test sticky behavior
  - Test downgrade logic
  - Test context window

- [ ] **Unit tests for calibration**
  - Test pattern generation
  - Test accuracy analysis
  - Test pattern eviction

- [ ] **Integration tests**
  - Test full routing pipeline
  - Test with real LLM calls
  - Test calibration workflow

### Priority 4: Documentation 📚
- [ ] **Add routing documentation to README.md**
  - How smart routing works
  - Configuration examples
  - Cost savings explanation
  
- [ ] **Create ROUTING.md**
  - Detailed architecture explanation
  - How to customize tiers
  - How to add custom patterns
  - Calibration tuning guide

- [ ] **Add inline code documentation**

### Priority 5: Analytics & Monitoring 📊
- [ ] **Cost tracking**
  - Track actual vs estimated costs
  - Calculate savings vs using single model
  - Export cost reports

- [ ] **Performance metrics**
  - Classification latency
  - Cache hit rates
  - Tier distribution

- [ ] **Routing dashboard**
  - Optional web UI for routing stats
  - Real-time cost tracking
  - Pattern management interface

### Priority 6: Advanced Features 🚀
- [ ] **Custom tier definitions**
  - Allow users to define their own tiers
  - Custom models per tier
  - Custom thresholds

- [ ] **Multi-model fallback**
  - If primary model fails, try next tier
  - Circuit breaker pattern

- [ ] **A/B testing**
  - Test different routing strategies
  - Compare cost vs quality

- [ ] **Export/import patterns**
  - Share learned patterns across deployments
  - Community pattern repository

## Configuration Reference

### Minimal Config
```json
{
  "routing": {
    "enabled": true
  }
}
```

### Full Config
See `config.example.json` in repository root.

### Key Settings
- `client_classifier.min_confidence`: 0.0-1.0 (default: 0.85)
  - Threshold for accepting client-side classification
  - Lower = more Layer 2 calls (more accurate, slower)
  - Higher = more Layer 1 calls (faster, less accurate)

- `sticky.context_window`: 1-20 (default: 5)
  - How many messages to look back for sticky routing

- `auto_calibration.interval`: "24h", "100_classifications", "1d"
  - How often to run auto-calibration

## File Locations

**Implementation**:
- `/projects/nanobot-turbo/nanobot/agent/router/` - Core routing logic
- `/projects/nanobot-turbo/nanobot/agent/stages/` - Pipeline integration
- `/projects/nanobot-turbo/nanobot/config/schema.py` - Configuration schema

**Configuration**:
- `~/.nanobot/config.json` - User configuration
- `~/.nanobot/workspace/memory/ROUTING_PATTERNS.json` - Learned patterns
- `~/.nanobot/workspace/analytics/routing_stats.json` - Analytics data

## Working with the Code

### Switch to correct directory
```bash
cd /projects/nanobot-turbo
```

### View routing info
```python
from nanobot.agent.stages import RoutingStage
from nanobot.config.loader import load_config

config = load_config()
stage = RoutingStage(config.routing)
print(stage.get_routing_info())
```

### Test classification
```python
from nanobot.agent.router import classify_content

decision, scores = classify_content("Write a Python function to sort a list")
print(f"Tier: {decision.tier}, Confidence: {decision.confidence}")
print(f"Scores: {scores.to_dict()}")
```

## Cost Savings Estimate

With typical usage distribution:
- 45% SIMPLE queries → $0.27/M (vs $75/M Opus) = 99.6% savings
- 35% MEDIUM queries → $0.60/M = 99.2% savings  
- 15% COMPLEX queries → $15/M = 80% savings
- 5% REASONING queries → $10/M = 87% savings

**Blended average**: ~$3.17/M vs $75/M = **96% cost savings**

## Git Commands

```bash
# Check status
git status

# View commits
git log --oneline -10

# Push changes
git push origin feature/smart-router

# Create PR (when ready)
gh pr create --title "Add smart LLM routing" --body "..."
```

## Questions or Issues?

1. Check this TODO file for current status
2. Review the commit history: `git log --oneline`
3. Check GitHub: https://github.com/jhonny-cinco-ai/nanobot-turbo
4. Review code in `nanobot/agent/router/`

---

**Last Updated**: 2026-02-09  
**Current Branch**: feature/smart-router  
**Next Priority**: Integrate RoutingStage into AgentLoop
