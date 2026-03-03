# Smart Web Tools - AI-Powered Web Content Extraction

Inspired by Claude Code's WebFetch tool, nanobot now includes **smart web tools** that use AI to extract and summarize web content intelligently.

## Overview

Traditional web scraping returns raw HTML or markdown, which can be overwhelming and contain irrelevant information. Smart web tools use a small, fast LLM (like Claude Haiku) to:

1. Fetch web pages
2. Convert HTML to markdown
3. **Extract only the information you need** based on your prompt
4. Cache results for 15 minutes (configurable)

This provides more focused, relevant responses similar to Claude Code's web capabilities.

## Features

### SmartWebFetchTool
- **AI-powered extraction**: Fetches URL and extracts specific information based on your prompt
- **Intelligent caching**: 15-minute default cache (configurable)
- **Model selection**: Use fast/cheap models like Haiku for extraction
- **Proxy support**: Works with HTTP/SOCKS5 proxies
- **Error handling**: Clear error messages with troubleshooting hints

### SmartWebSearchTool
- **Search + Analysis**: Searches web and analyzes top results with AI
- **Synthesis**: Combines information from multiple sources
- **Focus areas**: Specify what information to prioritize
- **Source citation**: References results in the output

## Configuration

### Enable Smart Web Tools

Add to your `~/.nanobot/config.json`:

```json
{
  "tools": {
    "web": {
      "smart": {
        "enabled": true,
        "extractionModel": "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
        "maxChars": 50000,
        "cacheTtl": 900
      }
    }
  }
}
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable smart web tools |
| `extractionModel` | string | `""` | Model for extraction (empty = use default, recommend Haiku) |
| `maxChars` | integer | `50000` | Maximum characters to fetch from URLs |
| `cacheTtl` | integer | `900` | Cache time-to-live in seconds (15 minutes) |

## Usage Examples

### Smart Web Fetch

**Basic Example:**
```json
{
  "tool": "smart_web_fetch",
  "url": "https://docs.anthropic.com/en/docs/about-claude/models",
  "prompt": "What are the latest Claude models and their capabilities?"
}
```

**Response:**
```
**Source:** https://platform.claude.com/docs/en/docs/about-claude/models

The latest Claude models are:

1. **Claude Opus 4.6** - The most intelligent model for building agents and coding
   - 200K context window (1M with beta)
   - Extended and adaptive thinking support
   - $5/input MTok, $25/output MTok

2. **Claude Sonnet 4.6** - Best combination of speed and intelligence
   - 200K context window (1M with beta)
   - $3/input MTok, $15/output MTok

3. **Claude Haiku 4.5** - Fastest model with near-frontier intelligence
   - 200K context window
   - $1/input MTok, $5/output MTok
```

### Smart Web Search

**Basic Search:**
```json
{
  "tool": "smart_web_search",
  "query": "Python async best practices 2025",
  "count": 3
}
```

**Focused Search:**
```json
{
  "tool": "smart_web_search",
  "query": "AWS Bedrock pricing",
  "focus": "cost comparison with direct Anthropic API",
  "count": 5
}
```

## Comparison with Regular Web Tools

| Feature | web_fetch | smart_web_fetch |
|---------|-----------|-----------------|
| **Output** | Raw markdown | AI-extracted information |
| **Relevance** | All content | Only what you asked for |
| **Size** | Full page | Concise summary |
| **Caching** | None | 15-minute cache |
| **LLM calls** | 0 | 1 per fetch |
| **Use case** | Full content needed | Specific info extraction |

## Cost Considerations

Smart web tools make LLM calls for extraction:

### SmartWebFetch
- **1 LLM call per URL** (cached for 15 minutes)
- Recommended model: Claude Haiku ($1/MTok input, $5/MTok output)
- Typical cost: ~$0.001-0.005 per page

### SmartWebSearch
- **N+1 LLM calls** (N = number of results to analyze, +1 for synthesis)
- For 3 results: ~$0.004-0.015 per search
- Caching reduces costs for repeated queries

### Cost Optimization Tips

1. **Use Haiku for extraction**: 10x cheaper than Sonnet, sufficient for extraction
2. **Enable caching**: Set `cacheTtl: 900` (15 min) or higher
3. **Limit result count**: Use `count: 3` instead of `count: 10` for searches
4. **Use regular tools when appropriate**: If you need full content, use `web_fetch`

## Architecture

```
┌─────────────────┐
│  User Request   │ "What are the latest features?"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ SmartWebFetch   │ 1. Fetch URL
└────────┬────────┘    2. Convert to markdown
         │
         ▼
┌─────────────────┐
│   WebFetchTool  │ Standard web fetching
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  LLM Extraction │ 3. Extract info based on prompt
│   (Haiku/Fast)  │    using small, fast model
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Cache Result  │ 4. Cache for 15 minutes
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Extracted Info  │ Only relevant information returned
└─────────────────┘
```

## Agent Usage

When nanobot's agent uses smart web tools, it looks like this:

```
User: "Search for AWS Bedrock documentation and tell me how to set it up"

Agent: I'll search for AWS Bedrock setup information
  → calls smart_web_search(query="AWS Bedrock setup", count=3)

Smart Web Search:
  1. Fetches top 3 search results
  2. Uses LLM to extract setup info from each
  3. Synthesizes findings into comprehensive answer

Agent: Based on the documentation, here's how to set up AWS Bedrock:
  1. Enable model access in the AWS Console...
  2. Configure AWS credentials...
  [Comprehensive answer with citations]
```

## When to Use Smart Web Tools

### ✅ Use SmartWebFetch when:
- You need specific information from a page
- You want to avoid information overload
- You're querying documentation sites
- You need summarization of long articles

### ✅ Use SmartWebSearch when:
- You need to research a topic
- You want synthesized information from multiple sources
- You need current information (beyond model training data)

### ❌ Use Regular Tools when:
- You need the full, raw content
- You're scraping structured data
- You want to minimize LLM calls for cost
- You need exact HTML structure

## Advanced Configuration

### Per-Agent Configuration

Different agents can use different extraction models:

```json
{
  "agents": {
    "defaults": {
      "model": "bedrock/anthropic.claude-sonnet-4-6"
    }
  },
  "tools": {
    "web": {
      "smart": {
        "enabled": true,
        "extractionModel": "bedrock/anthropic.claude-3-haiku-20240307-v1:0"
      }
    }
  }
}
```

Here, the main agent uses Sonnet 4.6 for reasoning, but smart web tools use Haiku for cost-effective extraction.

### Proxy Configuration

Smart web tools inherit proxy settings:

```json
{
  "tools": {
    "web": {
      "proxy": "http://127.0.0.1:7890",
      "smart": {
        "enabled": true
      }
    }
  }
}
```

### Custom Cache TTL

Adjust cache duration based on content freshness needs:

```json
{
  "tools": {
    "web": {
      "smart": {
        "enabled": true,
        "cacheTtl": 3600  // 1 hour for slowly-changing content
      }
    }
  }
}
```

## Troubleshooting

### Smart web tools not available

**Symptom**: Agent doesn't have `smart_web_fetch` tool

**Solution**: Enable in config:
```json
{"tools": {"web": {"smart": {"enabled": true}}}}
```

### Extraction quality is poor

**Symptom**: Extracted information is incomplete or irrelevant

**Solutions**:
1. **Improve your prompt**: Be more specific about what you want
2. **Increase max_chars**: Raise `maxChars` to capture more content
3. **Use a better model**: Try Sonnet instead of Haiku for complex extractions

### High LLM costs

**Symptom**: Unexpected costs from smart web usage

**Solutions**:
1. **Use Haiku**: Set `extractionModel: "bedrock/anthropic.claude-3-haiku-20240307-v1:0"`
2. **Increase cache TTL**: Set `cacheTtl: 1800` (30 minutes)
3. **Limit search results**: Use `count: 3` instead of higher values
4. **Use regular tools for full content**: Switch to `web_fetch` when appropriate

## Examples

### Research Task

```python
# Agent automatically uses smart web search
user: "Research best practices for async Python in 2025"

agent → smart_web_search(
    query="Python async best practices 2025",
    focus="performance and error handling",
    count=5
)

# Returns synthesized information from 5 sources
```

### Documentation Lookup

```python
user: "How do I enable extended thinking in Claude API?"

agent → smart_web_fetch(
    url="https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking",
    prompt="How to enable extended thinking feature"
)

# Returns: "Extended thinking can be enabled by..."
```

### Multi-Source Comparison

```python
user: "Compare AWS Bedrock vs Anthropic API pricing"

agent → smart_web_search(
    query="AWS Bedrock Anthropic pricing comparison",
    focus="cost per million tokens",
    count=4
)

# Synthesizes pricing info from multiple sources
```

## Implementation Details

### Tool Flow

1. **Request**: Agent calls `smart_web_fetch(url, prompt)`
2. **Cache Check**: Check if result is cached (key: url + prompt)
3. **Fetch**: Use `WebFetchTool` to get content
4. **Extract**: Send content + prompt to LLM
5. **Cache**: Store result with timestamp
6. **Return**: Formatted result with source citation

### LLM Prompt Template

The extraction prompt is structured as:

```
You are a web content analyzer. Extract the requested information from the following web page content.

URL: {url}

User Request: {prompt}

Web Page Content:
{content}

Instructions:
- Extract only the information requested by the user
- Be concise but complete
- If the information isn't in the page, say so
- Format your response in a clear, readable way
- Do not include information not relevant to the user's request

Response:
```

This ensures focused, relevant extraction.

## Contributing

To add features to smart web tools:

1. **Enhance SmartWebFetchTool**: Add new extraction modes
2. **Improve SmartWebSearchTool**: Add source ranking/filtering
3. **Add new smart tools**: Follow the same pattern

See `nanobot/agent/tools/smart_web.py` for implementation details.

## Credits

Inspired by Claude Code's WebFetch tool by Anthropic. Adapted for nanobot with caching, configurable models, and search capabilities.

## License

Same as nanobot (MIT License)
