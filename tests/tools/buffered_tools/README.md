# Buffered Tools Tests

Tests for the buffered tools framework and image generation.

## Test Structure

```
tests/tools/buffered_tools/
├── __init__.py
├── test_image_generation.py    # Main test suite
└── output/                      # Generated test images
```

## Running Tests

```bash
# Run all image generation tests
cd nanobot
.venv\Scripts\python tests\tools\buffered_tools\test_image_generation.py

# Or with pytest
.venv\Scripts\python -m pytest tests/tools/buffered_tools/test_image_generation.py -v
```

## Test Suite

### TEST 1: Multi-Agent Chinese Prompt Generation
Tests the 4-agent system that generates Chinese prompts:
- Agent 1: Conversation analysis (对话分析)
- Agent 2: Style extraction (风格提取)
- Agent 3: Cultural adaptation (文化适应)
- Agent 4: Prompt synthesis (提示合成)

**Expected**: Chinese prompt with cultural elements

### TEST 2: Gemini API Connection
Tests basic Gemini API connectivity with text generation.

**Expected**: Successful text response from Gemini

### TEST 3: Gemini Image Generation
Tests actual image generation with Gemini/Imagen.

**Expected**: Image generated and saved to `output/` directory

**Note**: This test may fail if your Gemini API key doesn't have image generation enabled. The API key `AIzaSyC3PIUzoR5VQcd1EEcAKjO_nlY9OKxUAuc` is valid for text but may need upgrade for images.

### TEST 4: Async Image Tool
Tests non-blocking async generation with callbacks.

**Expected**: 
- Task starts immediately
- Progress messages sent
- Result (success/error) sent to channel

### TEST 5: Buffered Tools Integration
Tests tool registration and execution.

**Expected**: Tools create and execute without errors

## Environment Variables

Set these before running tests:

```bash
GOOGLE_GENERATIVE_AI_API_KEY=AIzaSyC3PIUzoR5VQcd1EEcAKjO_nlY9OKxUAuc
```

## Known Issues

### Gemini Image Generation
The Gemini API key provided works for text generation but image generation requires:
1. Imagen API access enabled, OR
2. Gemini model with image output capability

Current error (expected):
```
Model does not support the requested response modalities: image,text
```

**Solution**: Use OpenAI or Stability AI provider instead, or upgrade Gemini API access.

## Test Output

Tests create output in:
- `tests/tools/buffered_tools/output/` - Generated images
- Console output with detailed logs

## Success Criteria

- 4/5 tests should pass (all except Gemini image generation)
- Multi-agent prompt generation works perfectly
- Async non-blocking flow works
- Tool integration works

## Troubleshooting

### "API Key not set"
Make sure `GOOGLE_GENERATIVE_AI_API_KEY` is set in environment.

### "Model does not support image modalities"
Your Gemini API key doesn't have image generation enabled. This is expected for free tier keys. Use alternative provider.

### Import errors
Run tests from the `nanobot` directory, not from subdirectories.
