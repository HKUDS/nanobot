# Memory Rollout Settings

Configuration sources for rollout behavior:

1. Global config (`~/.nanobot/config.json`)
- `agents.defaults.memoryRolloutMode`
- `agents.defaults.memoryTypeSeparationEnabled`
- `agents.defaults.memoryRouterEnabled`
- `agents.defaults.memoryReflectionEnabled`
- `agents.defaults.memoryShadowMode`
- `agents.defaults.memoryShadowSampleRate`
- `agents.defaults.memoryVectorHealthEnabled`
- `agents.defaults.memoryAutoReindexOnEmptyVector`
- `agents.defaults.memoryHistoryFallbackEnabled`
- `agents.defaults.memoryFallbackAllowedSources`
- `agents.defaults.memoryFallbackMaxSummaryChars`
- `agents.defaults.memoryRolloutGateMinRecallAtK`
- `agents.defaults.memoryRolloutGateMinPrecisionAtK`
- `agents.defaults.memoryRolloutGateMaxAvgMemoryContextTokens`
- `agents.defaults.memoryRolloutGateMaxHistoryFallbackRatio`

Precedence:
- Environment variables (`NANOBOT_MEMORY_*`) override all.
- Global config values from `~/.nanobot/config.json` are the primary runtime settings.
- Code defaults are used when global values are not set.

Recommended rollout progression:
1. `memory_rollout_mode=enabled`
2. `memory_shadow_mode=true` with `memory_shadow_sample_rate=0.2`
3. (Optional deterministic benchmark) seed corpus:
   `nanobot memory eval --seeded-profile case/memory_seed_profile.json --seeded-events case/memory_seed_events.jsonl --seed-only`
4. Run `nanobot memory eval --cases-file case/memory_eval_cases.json --export`
5. Use `nanobot memory inspect` to confirm:
   - `vector points` > 0
   - `mem0 get_all count` > 0
   - `history rows` can be > 0, but `vector health` should be `healthy`
   - `history_fallback_ratio` gate remains <= configured threshold
6. Promote only if rollout gates pass consistently.
7. Roll back quickly with `memory_rollout_mode=disabled`.
