# Nanobot Tests

This directory contains comprehensive tests for the nanobot AI assistant framework.

## Quick Start

### Prerequisites

Before running tests, ensure you have the following installed:

```bash
# Install the package in development mode
pip install -e .

# Install test dependencies
pip install pytest pytest-asyncio pytest-cov pytest-mock

# Install Playwright browsers (for browser tool tests)
playwright install chromium
```

### Running Tests

#### Run All Tests
```bash
pytest
```

#### Run Specific Test File
```bash
pytest tests/test_session.py
```

#### Run with Coverage
```bash
pytest --cov=nanobot --cov-report=html
# View coverage report
open htmlcov/index.html
```

#### Run with Verbose Output
```bash
pytest -v
```

#### Run Only Failed Tests
```bash
pytest --lf
```

#### Run Specific Test
```bash
pytest tests/test_session.py::test_session_creation
```

#### Run Tests with Markers
```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run only slow tests
pytest -m slow
```

#### Run Tests in Parallel
```bash
pytest -n auto
```

#### Run Tests with Detailed Output
```bash
pytest -vv --tb=short
```

## Test Categories

### Unit Tests
Unit tests focus on testing individual components in isolation.

- **Session Management** (`test_session.py`): Tests for conversation session handling
  - Session creation and initialization
  - Message storage and retrieval
  - Session lifecycle management
  - Session key generation and validation

- **Channel Base** (`test_channel_base.py`): Tests for base channel functionality
  - Channel initialization
  - Message sending and receiving
  - Channel state management
  - Error handling

- **Browser Tool** (`test_browser_tool.py`): Tests for browser automation
  - Browser initialization
  - Page navigation
  - Element interaction
  - Screenshot capture

- **Provider Vision** (`test_provider_vision.py`): Tests for provider vision support
  - Image processing
  - Vision API integration
  - Multi-modal message handling

### Integration Tests
Integration tests verify that multiple components work together correctly.

- **Agent Loop** (`test_agent_loop_integration.py`): Tests for agent loop with browser tool
  - End-to-end agent workflows
  - Tool integration
  - Message flow through the system
  - Error recovery

## Test Coverage Goals

- **Overall Coverage**: 80%+
- **Critical Paths**: 95%+
- **Channel Implementations**: 75%+
- **Session Management**: 90%+
- **Browser Tool**: 85%+
- **Provider Integration**: 80%+

### Viewing Coverage Reports

After running tests with coverage, generate and view the report:

```bash
# Generate HTML coverage report
pytest --cov=nanobot --cov-report=html

# Open the report in your browser
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

## Test Configuration

### pytest Configuration

The project uses `pyproject.toml` for pytest configuration:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "-v",
    "--strict-markers",
    "--tb=short",
]
markers = [
    "unit: Unit tests",
    "integration: Integration tests",
    "slow: Slow running tests",
    "browser: Tests requiring browser",
]
```

### Environment Variables

Some tests may require environment variables:

```bash
# Optional: Set API keys for provider tests
export OPENAI_API_KEY="your-key-here"
export ANTHROPIC_API_KEY="your-key-here"

# Optional: Set test workspace path
export TEST_WORKSPACE="/tmp/nanobot-test"
```

## Fixtures

The `conftest.py` file provides shared fixtures for:

- **Mock workspaces**: Temporary workspace directories for file operations
- **Mock message buses**: Simulated message bus for testing communication
- **Mock LLM providers**: Fake providers for testing without API calls
- **Mock configurations**: Test configuration objects
- **Sample data**: Pre-configured images, messages, and test data
- **Async helpers**: Utilities for async test setup and teardown
- **File system helpers**: Functions for creating and managing test files

### Using Fixtures

Fixtures are automatically discovered by pytest. You can use them by adding them as parameters to your test functions:

```python
def test_with_fixture(mock_workspace, mock_provider):
    """Test using shared fixtures."""
    # mock_workspace and mock_provider are automatically injected
    assert mock_workspace is not None
    assert mock_provider is not None
```

### Creating Custom Fixtures

Add custom fixtures to `conftest.py`:

```python
@pytest.fixture
def custom_data():
    """Provide custom test data."""
    return {"key": "value", "number": 42}
```

## Writing New Tests

### Guidelines

1. **Follow naming conventions**: `test_<module>.py` for files, `test_<function>` for functions
2. **Use descriptive test names**: Names should clearly describe what is being tested
3. **Use Arrange-Act-Assert pattern**: Organize tests into setup, execution, and verification
4. **Leverage fixtures**: Reuse fixtures from `conftest.py` to avoid duplication
5. **Test both success and failure cases**: Ensure comprehensive coverage
6. **Use `@pytest.mark.asyncio` for async tests**: Required for async test functions
7. **Keep tests independent**: Each test should be able to run in isolation
8. **Use appropriate assertions**: Be specific about what you're testing

### Example Test

```python
import pytest
from nanobot.session.manager import Session

def test_session_creation():
    """Test Session dataclass initialization."""
    # Arrange
    expected_key = "test:123"

    # Act
    session = Session(key=expected_key)

    # Assert
    assert session.key == expected_key
    assert session.messages == []
```

### Example Async Test

```python
import pytest
from nanobot.agent.loop import AgentLoop

@pytest.mark.asyncio
async def test_agent_loop_execution(mock_provider, mock_workspace):
    """Test agent loop execution with mocked dependencies."""
    # Arrange
    agent_loop = AgentLoop(provider=mock_provider, workspace=mock_workspace)

    # Act
    result = await agent_loop.run("test message")

    # Assert
    assert result is not None
    assert result.status == "completed"
```

### Example Test with Mocking

```python
from unittest.mock import Mock, AsyncMock, patch

def test_with_mock():
    """Test with mocked dependency."""
    # Arrange
    mock_provider = Mock()
    mock_provider.chat = AsyncMock(return_value="test response")

    # Act
    result = await mock_provider.chat("test message")

    # Assert
    assert result == "test response"
    mock_provider.chat.assert_called_once_with("test message")
```

## Async Testing

All async tests must use the `@pytest.mark.asyncio` decorator:

```python
@pytest.mark.asyncio
async def test_async_operation():
    """Test async operation."""
    result = await some_async_function()
    assert result is not None
```

### Async Test Best Practices

- Always use `@pytest.mark.asyncio` decorator
- Use `pytest-asyncio` for async test execution
- Handle async context managers properly
- Clean up async resources in teardown
- Use `pytest.raises` for testing async exceptions:

```python
@pytest.mark.asyncio
async def test_async_error_handling():
    """Test async error handling."""
    with pytest.raises(ValueError):
        await async_function_that_raises()
```

## Mocking

Use `unittest.mock` for mocking external dependencies:

```python
from unittest.mock import Mock, AsyncMock, patch, MagicMock

def test_with_mock():
    """Test with mocked dependency."""
    mock_provider = Mock()
    mock_provider.chat = AsyncMock()
    # ... test code
```

### Common Mocking Patterns

#### Mocking Functions
```python
from unittest.mock import patch

@patch('nanobot.providers.openai.chat')
def test_with_patched_function(mock_chat):
    """Test with patched function."""
    mock_chat.return_value = "mocked response"
    result = some_function_using_chat()
    assert result == "mocked response"
```

#### Mocking Classes
```python
def test_with_mocked_class():
    """Test with mocked class."""
    mock_instance = MagicMock()
    mock_instance.method.return_value = "result"
    # Use mock_instance in your test
```

#### Async Mocking
```python
@pytest.mark.asyncio
async def test_with_async_mock():
    """Test with async mock."""
    mock_async_func = AsyncMock(return_value="async result")
    result = await mock_async_func()
    assert result == "async result"
```

## CI/CD

Tests are configured to run on GitHub Actions with:

- **Python Versions**: 3.11 and 3.12
- **Coverage Reporting**: Automatic coverage tracking
- **Automatic Execution**: Tests run on push and pull requests
- **Parallel Execution**: Tests run in parallel for faster feedback

### CI Configuration

The CI workflow is defined in `.github/workflows/test.yml` and includes:

1. Environment setup
2. Dependency installation
3. Test execution
4. Coverage reporting
5. Result reporting

### Running Tests Locally Before Pushing

```bash
# Run all tests with coverage
pytest --cov=nanobot --cov-report=term-missing

# Check if coverage meets requirements
pytest --cov=nanobot --cov-fail-under=80
```

## Troubleshooting

### Tests Fail with Import Errors

**Problem**: Module import errors when running tests

**Solution**: Make sure you've installed the package in development mode:
```bash
pip install -e .
```

### Async Tests Hang

**Problem**: Async tests hang or timeout

**Solution**: Ensure you're using `pytest-asyncio` with the correct configuration in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### Playwright Tests Fail

**Problem**: Browser-related tests fail

**Solution**: Install Playwright browsers:
```bash
playwright install chromium
```

### Coverage Report Not Generated

**Problem**: Coverage report is not created

**Solution**: Install pytest-cov:
```bash
pip install pytest-cov
```

### Tests Run Slowly

**Problem**: Tests take too long to execute

**Solution**: Run tests in parallel:
```bash
pytest -n auto
```

Or skip slow tests:
```bash
pytest -m "not slow"
```

### Fixture Not Found

**Problem**: Pytest can't find a fixture

**Solution**: Ensure the fixture is defined in `conftest.py` or imported correctly:
```python
# In conftest.py
@pytest.fixture
def my_fixture():
    return "value"

# In test file
def test_using_fixture(my_fixture):
    assert my_fixture == "value"
```

## Contributing

When adding new features or modifying existing code:

1. **Write tests first** (TDD approach): Define expected behavior before implementation
2. **Ensure all tests pass**: Run the full test suite before committing
3. **Maintain or improve coverage**: Check that coverage doesn't decrease
4. **Update this README**: Add documentation for new test files or patterns
5. **Use descriptive commit messages**: Clearly explain what was changed and why
6. **Run tests locally**: Verify tests pass before pushing

### Test Review Checklist

- [ ] All tests pass locally
- [ ] Coverage meets or exceeds requirements
- [ ] New tests follow project conventions
- [ ] Documentation is updated
- [ ] No flaky tests (tests that sometimes fail)
- [ ] Tests are independent and can run in any order

## Best Practices

### Test Organization

- Group related tests in the same file
- Use test classes for organizing related test methods
- Keep test files focused on a single module or feature

### Test Data Management

- Use fixtures for reusable test data
- Keep test data minimal and focused
- Avoid hardcoding values that might change

### Error Testing

- Test both expected and unexpected errors
- Verify error messages are appropriate
- Test error recovery mechanisms

### Performance Testing

- Mark slow tests with `@pytest.mark.slow`
- Use `@pytest.mark.timeout` for tests that should complete quickly
- Consider performance implications when adding tests

## Resources

### Documentation

- [pytest Documentation](https://docs.pytest.org/) - Comprehensive pytest guide
- [pytest-asyncio Documentation](https://pytest-asyncio.readthedocs.io/) - Async testing with pytest
- [pytest-mock Documentation](https://pytest-mock.readthedocs.io/) - Mocking utilities
- [pytest-cov Documentation](https://pytest-cov.readthedocs.io/) - Coverage reporting

### Project Documentation

- [nanobot README](../README.md) - Main project documentation
- [nanobot Architecture](../docs/architecture.md) - System architecture overview
- [nanobot API Reference](../docs/api.md) - API documentation

### Testing Resources

- [Python Testing Best Practices](https://docs.python-guide.org/writing/tests/)
- [Effective Python Testing with Pytest](https://realpython.com/pytest-python-testing/)
- [Test-Driven Development](https://martinfowler.com/bliki/TestDrivenDevelopment.html)

## Support

If you encounter issues with tests:

1. Check this README for common solutions
2. Review the troubleshooting section
3. Check existing GitHub issues
4. Create a new issue with:
   - Python version
   - pytest version
   - Full error message
   - Steps to reproduce
   - Expected vs actual behavior
