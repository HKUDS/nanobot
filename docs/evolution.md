# Nanobot Evolution Engine

The evolution engine is a controlled improvement pipeline, not unrestricted
self-modification. It separates five steps:

1. **Observe** completed turns using bounded telemetry.
2. **Reflect** with deterministic thresholds and evidence IDs.
3. **Propose** reviewable changes with an explicit risk level.
4. **Evaluate** candidate metrics against a baseline.
5. **Promote** only an evaluated artifact allowed by policy.

Promotion never edits source code, configuration, permissions, secrets, safety
rules, or the constitution. Those changes remain ordinary reviewed development
work. This makes repeated execution safe and preserves rollback/audit evidence.

## Configuration

```json
{
  "agents": {
    "defaults": {
      "evolution": {
        "enabled": true,
        "mode": "observe",
        "storageDir": "evolution",
        "captureContent": false,
        "includeSystemTurns": false,
        "reflectionMinSamples": 10,
        "reflectionWindow": 100,
        "autoReflectEvery": 20,
        "optimizationWindow": 100,
        "targetModelRounds": 4,
        "targetOutputTokens": 2000,
        "autoApplyMaxRisk": 0
      }
    }
  }
}
```

Modes:

- `observe`: record telemetry only; never generate or apply changes automatically.
- `propose`: periodically generate evidence-backed proposals; never apply them.
- `controlled`: allows promotion of passing, policy-allowed artifacts up to the
  configured risk. Promotion still does not mutate production code.

`captureContent` defaults to `false`. In that mode the store contains salted
hashes, lengths, turn-local tool names/counts, outcomes, latency, model and token
usage, but no raw prompt or response. Evolution data is written beneath the
workspace with directory mode `0700` and file mode `0600`.

The report includes a deterministic token-optimization section. It identifies
turns above the configured model-round and output-token targets and calculates a
hypothetical threshold scenario. It is **not measured waste or a verified saving**:
long tasks may need those rounds, and cached tokens have different costs. Actual
savings require a quality-controlled before/after evaluation. This is observation
only: it performs no LLM calls and never edits prompts, memory, routing, or runtime
configuration.

## Risk model

| Risk | Meaning | Autonomous behavior |
|---|---|---|
| 0 | observation/checklist artifact | promotion possible only in controlled mode |
| 1 | reversible workflow experiment | bounded by configured policy |
| 2 | behavior, capability, cost, or data-access change | explicit user approval |
| 3 | safety/permission/audit boundary | prohibited |

The following classes are code-level forbidden boundaries: self-granting
permissions, expanding secret access, disabling audit, deleting a source of
truth, modifying the constitution, removing safety constraints, and unreviewed
production deployment.

## Commands

```bash
nanobot-evolution status
nanobot-evolution reflect
nanobot-evolution report --write
nanobot-evolution evaluate experiment.json
```

An experiment manifest contains `id`, `change_type`, `risk`, `baseline`,
`candidate`, optional `higher_is_better`, `critical_metrics`, and
`minimum_improvement`. A critical regression always fails evaluation.

## Stored layout

```text
workspace/evolution/
├── observations/experiences.jsonl
├── proposals/
├── experiments/
├── evaluations/
├── accepted/
├── rejected/
├── reports/
├── audit.jsonl
└── .identity_salt
```

The JSONL logs are append-only at the application layer. Corrupt partial lines
are ignored during reads, while valid prior records remain available.

## Operational rollout

Start in `observe` for at least one representative sampling period. Inspect the
report, tune thresholds, then move to `propose`. `controlled` should only be
enabled after regression benchmarks exist. Always keep `captureContent=false`
unless the privacy trade-off is explicitly accepted.
