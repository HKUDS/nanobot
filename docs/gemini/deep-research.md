# Deep Research

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/deep-research

## What It Is

Autonomous multi-step research agent. Plans, searches, reads, iterates, and produces detailed cited reports. Powered by Gemini 3.1 Pro.

## Gemini API Capabilities

### Model

`deep-research-pro-preview-12-2025` (Preview)

### How it works

1. Receives research query
2. Plans research strategy
3. Executes Google Search queries (~80–160 per task)
4. Reads and analyzes web content
5. Iterates and refines
6. Produces long-form cited report

### Features

- **Default tools:** Google Search, URL context, web browsing
- **File Search** — can search private uploaded documents
- **Multimodal input:** text, images, PDFs, audio, video
- **Citation tracking** for source verification
- **Streaming** with thought summaries and reconnection
- **Steerable output** — control tone, format, organization

### Execution

- Requires `background=True` (async)
- Uses Interactions API (not `generate_content`)
- Max research time: 60 minutes (typical ~20 min)
- Polling for status: `in_progress` → `completed`/`failed`

### Cost

- Standard task: ~80 queries, ~250K input tokens
- Complex task: ~160 queries, ~900K input tokens
- Typical: $2–$5 per research task
- Context caching reduces cost by 50–70%

### Limitations

- No custom function calling tools
- No structured outputs
- No human-approved planning step
- No audio inputs

## Nanobot Implementation

Not implemented. No autonomous research agent or Interactions API usage.

**What Deep Research would enable:**
- "Research X and write a report" as a single command
- Automated multi-source web research
- Cited long-form output
- Could be wired as an agent tool
