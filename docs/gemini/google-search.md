# Google Search Grounding

> **Status: Not implemented** — scorpion uses Brave Search API
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/google-search

## What It Is

Ground model responses with real-time web search results. The model automatically generates search queries, retrieves results, and synthesizes them into cited answers.

## Gemini API Capabilities

### How it works

1. Model analyzes query, decides if web search helps
2. Automatically generates and executes search queries
3. Retrieves and synthesizes results
4. Returns text with grounding metadata and citations

### Configuration

```python
grounding_tool = types.Tool(google_search=types.GoogleSearch())
config = types.GenerateContentConfig(tools=[grounding_tool])
```

### Response metadata

- `webSearchQueries` — queries the model generated
- `searchEntryPoint` — HTML/CSS for search suggestions rendering
- `groundingChunks` — source URIs and titles
- `groundingSupports` — text span → source mappings with startIndex/endIndex

### Pricing

- **Gemini 3:** billed per search query executed
- **Gemini 2.5:** billed per prompt

### Supported models

Gemini 3.1 Flash Image, 3 Pro Image, 3 Flash, 2.5 Pro/Flash/Flash-Lite

### Combinable with

Code Execution, URL Context

## Nanobot Implementation

**Current web search:** Brave Search API (`scorpion/agent/tools/web.py`)

```python
# Agent tool: WebSearchTool using Brave Search
# Requires separate Brave API key
```

Web search is implemented as an agent tool calling Brave's API, not as Gemini-native grounding. Results are returned as tool output text, not grounding metadata with citations.

**What Google Search grounding would enable:**
- No additional API key needed (uses Gemini key)
- Automatic search query generation by the model
- Source citations with precise text span attribution
- Search suggestions HTML rendering
- Eliminates Brave Search dependency
