# Gemini API Features

Complete reference of all Google Gemini API capabilities and their implementation status in scorpion.

**SDK:** `google-genai`
**Default model:** `gemini-2.5-flash`
**Docs:** https://ai.google.dev/gemini-api/docs

---

## Implementation Status

| # | Feature | Status | Doc |
|---|---------|--------|-----|
| 1 | [Text Generation](text-generation.md) | **Implemented** | [text-generation.md](text-generation.md) |
| 2 | [Thinking / Reasoning](thinking.md) | **Partial** — param exists, not wired | [thinking.md](thinking.md) |
| 3 | [Structured Output](structured-output.md) | Not implemented | [structured-output.md](structured-output.md) |
| 4 | [Function Calling](function-calling.md) | **Implemented** — AUTO mode only | [function-calling.md](function-calling.md) |
| 5 | [Image Understanding](image-understanding.md) | **Implemented** — inline base64 | [image-understanding.md](image-understanding.md) |
| 6 | [Video Understanding](video-understanding.md) | Not implemented | [video-understanding.md](video-understanding.md) |
| 7 | [Audio Understanding](audio-understanding.md) | Not implemented (uses ElevenLabs) | [audio-understanding.md](audio-understanding.md) |
| 8 | [Document Processing](document-processing.md) | Not implemented | [document-processing.md](document-processing.md) |
| 9 | [Image Generation — Nano Banana](image-generation-native.md) | **Implemented** | [image-generation-native.md](image-generation-native.md) |
| 10 | [Image Generation — Imagen](image-generation-imagen.md) | **Implemented** | [image-generation-imagen.md](image-generation-imagen.md) |
| 11 | [Video Generation — Veo](video-generation.md) | **Implemented** | [video-generation.md](video-generation.md) |
| 12 | [Text-to-Speech](text-to-speech.md) | Not implemented (uses ElevenLabs) | [text-to-speech.md](text-to-speech.md) |
| 13 | [Music Generation — Lyria](music-generation.md) | **Implemented** | [music-generation.md](music-generation.md) |
| 14 | [Live API](live-api.md) | **Partial** — music only | [live-api.md](live-api.md) |
| 15 | [Google Search Grounding](google-search.md) | Not implemented (uses Brave) | [google-search.md](google-search.md) |
| 16 | [Google Maps Grounding](google-maps.md) | Not implemented | [google-maps.md](google-maps.md) |
| 17 | [URL Context](url-context.md) | Not implemented (agent-side fetch) | [url-context.md](url-context.md) |
| 18 | [Code Execution](code-execution.md) | Not implemented (agent-side shell) | [code-execution.md](code-execution.md) |
| 19 | [Computer Use](computer-use.md) | Not implemented | [computer-use.md](computer-use.md) |
| 20 | [File Search / RAG](file-search.md) | Not implemented | [file-search.md](file-search.md) |
| 21 | [Deep Research](deep-research.md) | Not implemented | [deep-research.md](deep-research.md) |
| 22 | [Embeddings](embeddings.md) | Not implemented | [embeddings.md](embeddings.md) |
| 23 | [Context Caching](context-caching.md) | **Partial** — architecture ready, not wired | [context-caching.md](context-caching.md) |
| 24 | [Files API](files-api.md) | **Partial** — video download only | [files-api.md](files-api.md) |
| 25 | [Batch API](batch-api.md) | Not implemented | [batch-api.md](batch-api.md) |
| 26 | [Token Counting](token-counting.md) | **Partial** — usage metadata only | [token-counting.md](token-counting.md) |
| 27 | [Interactions API](interactions-api.md) | Not implemented | [interactions-api.md](interactions-api.md) |
| 28 | [Thought Signatures](thought-signatures.md) | Not implemented | [thought-signatures.md](thought-signatures.md) |
| 29 | [Safety Settings](safety-settings.md) | Not implemented | [safety-settings.md](safety-settings.md) |
| 30 | [OpenAI Compatibility](openai-compatibility.md) | Not applicable (native SDK) | [openai-compatibility.md](openai-compatibility.md) |

---

## Summary

| Status | Count |
|--------|-------|
| Fully implemented | 7 |
| Partially implemented | 5 |
| Not implemented | 18 |

**Fully implemented:** Text generation, Function calling, Image understanding, Image gen (Nano Banana), Image gen (Imagen), Video gen (Veo), Music gen (Lyria)

**Partially implemented:** Thinking (param not wired), Live API (music only), Context caching (arch ready), Files API (download only), Token counting (response metadata only)

**Using non-Gemini alternatives:** TTS (ElevenLabs), STT (ElevenLabs Scribe), Web search (Brave), URL fetch (agent httpx), Code exec (agent shell)
