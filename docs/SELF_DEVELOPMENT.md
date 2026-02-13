# Self-development Design (Feedback to Lessons)

## Overview

nanobot self-development is implemented as a lightweight feedback loop:

1. Detect mistakes or corrections
2. Convert them into structured lessons
3. Inject relevant lessons in future prompts
4. Reinforce or compact lessons over time

No embeddings or external retrieval systems are required.

## Files

- `memory/LESSONS.jsonl`: lesson store (persistent)
- `memory/LESSONS_AUDIT.jsonl`: lesson audit trail

Each lesson is a JSON object with fields like:

- `trigger`: when this lesson should apply
- `bad_action`: what failed previously
- `better_action`: what to do next time
- `scope`: `session` or `global`
- `confidence`: reliability score
- `hits`: usage/reinforcement counter

## Learning sources

### Tool feedback

When a tool returns an error result, nanobot learns a tool-specific lesson, for example:

- `trigger = tool:read_file:error`
- `better_action = Check path existence before calling read_file`

### User feedback

When users provide correction-style feedback, nanobot learns a response lesson. To reduce false positives:

- Previous assistant output must exist
- Message length must be within configured threshold
- By default, correction cue must appear as a prefix (`feedbackRequirePrefix=true`)

Example:

- `trigger = response:length`
- `better_action = Keep responses shorter unless detailed output is requested`

## Prompt injection

At context build time, nanobot selects top lessons by:

- scope match (`session` or `global`)
- confidence threshold (with time-decay)
- lightweight lexical relevance to current message (with normalized keywords)
- recency/hits tie-break

The selected lessons are injected into the `# Memory` section as `## Lessons`.

## Session to global promotion

To improve reuse without making the system heavy, nanobot can auto-promote repeated
session lessons into a global lesson when:

- lesson source is user feedback
- trigger is in `promotionTriggers`
- distinct user count reaches `promotionMinUsers`

Promotion is conservative: session lessons are kept, and a new global lesson is added.

## Compaction and reset

- `memory lessons list` inspects learned lessons
- `memory lessons disable|enable|delete` gives direct control over lesson behavior
- `memory lessons compact` deduplicates and caps lesson count
- `memory lessons reset` clears all lessons
- `memory list` and `memory delete` inspect/manage long-term snapshot items

## Configuration

See `agents.selfImprovement` in config:

- `enabled`
- `maxLessonsInPrompt`
- `minLessonConfidence`
- `maxLessons`
- `lessonConfidenceDecayHours`
- `feedbackMaxMessageChars`
- `feedbackRequirePrefix`
- `promotionEnabled`
- `promotionMinUsers`
- `promotionTriggers`

## Design goals

- Keep runtime fast (RAM-first)
- Keep behavior explainable (structured lessons)
- Keep implementation small and maintainable
