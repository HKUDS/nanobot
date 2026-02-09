# Router Tests

Comprehensive test suite for the smart routing system.

## Test Structure

```
tests/router/
├── __init__.py              # Test package
├── test_models.py           # Data model tests
├── test_classifier.py       # Client-side classifier tests
├── test_sticky.py          # Sticky routing tests
├── test_calibration.py     # Auto-calibration tests
├── test_integration.py     # Integration tests
└── README.md               # This file
```

## Running Tests

### Run all router tests
```bash
cd /projects/nanobot-turbo
python -m pytest tests/router/ -v
```

### Run specific test file
```bash
python -m pytest tests/router/test_classifier.py -v
```

### Run with coverage
```bash
python -m pytest tests/router/ --cov=nanobot.agent.router --cov-report=html
```

### Run specific test
```bash
python -m pytest tests/router/test_classifier.py::TestClientSideClassifier::test_classify_simple_query -v
```

## Test Categories

### 1. Model Tests (`test_models.py`)
Tests for data models and enums:
- `RoutingTier` enum values and string conversion
- `ClassificationScores` weighted calculations
- `RoutingDecision` creation and metadata
- `RoutingPattern` serialization/deserialization

### 2. Classifier Tests (`test_classifier.py`)
Tests for client-side classification:
- 14-dimension scoring system
- Pattern matching
- Confidence calibration (sigmoid)
- Tier determination
- Token estimation
- Tool requirement detection
- Edge cases (empty, unicode, long messages)

### 3. Sticky Routing Tests (`test_sticky.py`)
Tests for conversation context:
- Sticky tier maintenance
- Downgrade detection
- Context window behavior
- Integration with LLM fallback
- Session metadata updates

### 4. Calibration Tests (`test_calibration.py`)
Tests for auto-calibration:
- Classification recording
- Calibration triggering (time/count based)
- Accuracy analysis
- Pattern generation
- Pattern eviction
- File operations

### 5. Integration Tests (`test_integration.py`)
End-to-end tests:
- Full routing pipeline
- Complex message routing
- Sticky routing across messages
- LLM fallback integration
- Configuration integration
- Edge cases

## Test Fixtures

Common fixtures available:
- `tmp_path` - Temporary directory for file operations
- Mock objects for sessions, providers, etc.

## Writing New Tests

### Example: Adding a new classifier test

```python
def test_new_feature(self):
    """Test description."""
    classifier = ClientSideClassifier()
    
    # Test the feature
    decision, scores = classifier.classify("Test message")
    
    # Assert expected behavior
    assert decision.tier == RoutingTier.EXPECTED
    assert scores.some_dimension > 0.5
```

### Example: Adding async test

```python
@pytest.mark.asyncio
async def test_async_feature(self):
    """Test async functionality."""
    router = StickyRouter(client_classifier=classifier)
    
    decision = await router.classify("message", session)
    
    assert decision is not None
```

## Key Testing Principles

1. **Unit tests** - Test individual components in isolation
2. **Integration tests** - Test component interactions
3. **Edge cases** - Test empty inputs, unicode, long messages
4. **Mocking** - Mock external dependencies (LLM calls)
5. **Temp files** - Use `tmp_path` fixture for file operations

## Coverage Goals

- Models: 100%
- Classifier: 90%+
- Sticky routing: 90%+
- Calibration: 85%+
- Integration: 80%+

## Continuous Integration

Tests run automatically on:
- Pull requests
- Commits to main branch
- Daily scheduled runs

## Debugging Tests

### Verbose output
```bash
python -m pytest tests/router/ -v -s
```

### Stop on first failure
```bash
python -m pytest tests/router/ -x
```

### Show local variables on failure
```bash
python -m pytest tests/router/ -v --showlocals
```

## Common Issues

### Import errors
Make sure you're in the correct directory:
```bash
cd /projects/nanobot-turbo
```

### Async test failures
Ensure you use `@pytest.mark.asyncio` decorator.

### File permission errors
Tests use `tmp_path` fixture which handles permissions.

## Contributing

When adding new features:
1. Write tests first (TDD)
2. Ensure all tests pass
3. Add integration tests for new features
4. Update this README

## Test Data

Sample messages used in tests:
- Simple: "What is 2+2?", "Define photosynthesis"
- Medium: "Write a Python function", "Explain async/await"
- Complex: "Debug distributed system", "Fix race condition"
- Reasoning: "Prove this theorem", "Step by step analysis"
