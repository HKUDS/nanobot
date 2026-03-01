# Thought Signatures

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/thought-signatures

## What It Is

Encrypted representations of the model's internal reasoning that preserve context across multi-turn interactions. Critical for function calling round-trips in thinking models.

## Gemini API Capabilities

### How they work

- Appear as `thoughtSignature` fields in response content parts
- Encode reasoning state for continuity across turns
- Must be preserved and returned in conversation history

### Behavior by model

**Gemini 3 (mandatory):**
- Always included on first function call part
- Parallel calls: signature only on first part
- Omitting function call signatures → 400 error
- Non-function-call signatures: recommended but not validated

**Gemini 2.5 (optional):**
- Included in first parts regardless of type
- Returning them is optional but recommended for quality

### SDK handling

Official Google Gen AI SDKs handle signatures automatically in chat features. Manual extraction only needed for custom implementations.

### Rules

1. Extract signatures exactly as received
2. Preserve in identical positions when sending history back
3. For sequential steps, accumulate all prior signatures
4. Never modify signature content

## Nanobot Implementation

Not implemented. The message converter in `gemini_provider.py` does not extract or preserve `thoughtSignature` fields from responses.

**Impact:** Multi-turn function calling with thinking models may lose reasoning context between turns, potentially degrading response quality.

**What's needed:**
- Extract `thoughtSignature` from response parts
- Store in conversation history alongside function calls
- Return signatures in correct positions on subsequent requests
