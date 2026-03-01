# Structured Output

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/structured-output

## What It Is

Forces the model to respond in a specific JSON schema. Guarantees type-safe, predictable responses for data extraction, classification, and agentic workflows.

## Gemini API Capabilities

- **JSON mode:** `response_mime_type: "application/json"`
- **Schema enforcement:** `response_json_schema` with full JSON Schema support
- **Supported types:** string, number, integer, boolean, object, array, null
- **Schema features:** enum, minimum/maximum, minItems/maxItems, required, format (date-time), nullable via `["string", "null"]`
- **Streaming:** valid partial JSON chunks that concatenate into complete objects
- **Tool integration:** works alongside Google Search, Code Execution, File Search (Gemini 3)
- **Models:** Gemini 3.1 Pro, 3 Flash, 2.5 Pro/Flash/Flash-Lite, 2.0 Flash

## Nanobot Implementation

Not implemented. The `GenerateContentConfig` in `gemini_provider.py` does not set `response_mime_type` or `response_schema`.

Tool argument schemas are validated agent-side in `scorpion/agent/tools/base.py`, not via Gemini's native structured output.

**What's needed:**
```python
config = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=my_schema,
    ...
)
```
