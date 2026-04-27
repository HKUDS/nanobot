---
name: test-generator
description: "Generate comprehensive test cases for code across multiple languages and testing frameworks with intelligent coverage suggestions."
metadata: {"nanobot":{"emoji":"🧪","requires":{"bins":[]}}}
---

# Test Case Generator

Generate comprehensive test cases and suggestions for code across multiple languages and testing frameworks.

## Python Testing (pytest)

### Analyzing Code for Test Cases

When given Python code, generate tests covering:
- **Happy path**: Normal expected usage
- **Edge cases**: Empty inputs, None values, boundary conditions
- **Error cases**: Invalid inputs, exceptions
- **Type variations**: Different valid input types

### Test Template Structure

```python
import pytest
from module import function_to_test

class TestFunctionName:
    """Test suite for function_to_test"""
    
    def test_happy_path_basic(self):
        """Test normal expected behavior"""
        result = function_to_test(valid_input)
        assert result == expected_output
    
    def test_edge_case_empty_input(self):
        """Test with empty input"""
        result = function_to_test([])
        assert result == expected_empty_result
    
    def test_edge_case_none_input(self):
        """Test with None input"""
        with pytest.raises(TypeError):
            function_to_test(None)
    
    def test_boundary_minimum_value(self):
        """Test minimum boundary value"""
        result = function_to_test(0)
        assert result >= 0
    
    def test_boundary_maximum_value(self):
        """Test maximum boundary value"""
        result = function_to_test(sys.maxsize)
        assert isinstance(result, int)
    
    def test_error_invalid_type(self):
        """Test with invalid type"""
        with pytest.raises(TypeError):
            function_to_test("invalid")
    
    @pytest.mark.parametrize("input_val,expected", [
        (1, 2),
        (5, 10),
        (0, 0),
        (-1, -2),
    ])
    def test_parametrized_values(self, input_val, expected):
        """Test multiple input/output combinations"""
        assert function_to_test(input_val) == expected
```

### Test Coverage Analysis

```bash
# Install coverage tool
pip install pytest-cov

# Run tests with coverage
pytest --cov=mymodule --cov-report=html tests/

# View coverage report
open htmlcov/index.html

# Show missing lines
pytest --cov=mymodule --cov-report=term-missing

# Generate coverage badge
coverage-badge -o coverage.svg
```

### Fixture Patterns

```python
import pytest

@pytest.fixture
def sample_data():
    """Provide test data"""
    return {"key": "value", "items": [1, 2, 3]}

@pytest.fixture
def mock_database(monkeypatch):
    """Mock database connection"""
    class MockDB:
        def query(self, sql):
            return [{"id": 1, "name": "test"}]
    
    monkeypatch.setattr("myapp.database.connect", lambda: MockDB())
    return MockDB()

@pytest.fixture
def temp_file(tmp_path):
    """Create temporary file for testing"""
    file = tmp_path / "test.txt"
    file.write_text("test content")
    return file
```

## JavaScript Testing (Jest)

### Jest Test Template

```javascript
// Import the function to test
const { functionToTest } = require('./module');

describe('functionToTest', () => {
  // Happy path
  test('returns correct result for valid input', () => {
    const result = functionToTest(validInput);
    expect(result).toBe(expectedOutput);
  });
  
  // Edge cases
  test('handles empty input', () => {
    expect(functionToTest([])).toEqual([]);
  });
  
  test('handles null input', () => {
    expect(() => functionToTest(null)).toThrow(TypeError);
  });
  
  // Boundary conditions
  test('handles minimum value', () => {
    expect(functionToTest(0)).toBeGreaterThanOrEqual(0);
  });
  
  test('handles maximum value', () => {
    const result = functionToTest(Number.MAX_SAFE_INTEGER);
    expect(typeof result).toBe('number');
  });
  
  // Async tests
  test('async operation completes successfully', async () => {
    const result = await asyncFunction();
    expect(result).toBeDefined();
  });
  
  // Parameterized tests
  test.each([
    [1, 2],
    [5, 10],
    [0, 0],
    [-1, -2],
  ])('functionToTest(%i) returns %i', (input, expected) => {
    expect(functionToTest(input)).toBe(expected);
  });
});
```

### Mock Patterns

```javascript
// Mock entire module
jest.mock('./api', () => ({
  fetchData: jest.fn(() => Promise.resolve({ data: 'mocked' }))
}));

// Spy on method
const spy = jest.spyOn(object, 'method');
expect(spy).toHaveBeenCalledWith(expectedArg);

// Mock implementation
const mockFn = jest.fn((x) => x * 2);
expect(mockFn(5)).toBe(10);
expect(mockFn).toHaveBeenCalledWith(5);
```

### Coverage Configuration

```json
// package.json
{
  "jest": {
    "collectCoverage": true,
    "coverageDirectory": "coverage",
    "coverageThreshold": {
      "global": {
        "branches": 80,
        "functions": 80,
        "lines": 80,
        "statements": 80
      }
    }
  }
}
```

## Java Testing (JUnit 5)

### JUnit Test Template

```java
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.CsvSource;
import static org.junit.jupiter.api.Assertions.*;

@DisplayName("Tests for MyClass")
class MyClassTest {
    
    private MyClass instance;
    
    @BeforeEach
    void setUp() {
        instance = new MyClass();
    }
    
    @Test
    @DisplayName("Should return expected result for valid input")
    void testHappyPath() {
        int result = instance.calculate(5);
        assertEquals(10, result);
    }
    
    @Test
    @DisplayName("Should throw exception for null input")
    void testNullInput() {
        assertThrows(IllegalArgumentException.class, () -> {
            instance.calculate(null);
        });
    }
    
    @ParameterizedTest
    @ValueSource(ints = {1, 2, 3, 4, 5})
    @DisplayName("Should handle positive integers")
    void testPositiveIntegers(int input) {
        assertTrue(instance.calculate(input) > 0);
    }
    
    @ParameterizedTest
    @CsvSource({
        "1, 2",
        "5, 10",
        "0, 0",
        "-1, -2"
    })
    @DisplayName("Should return correct results for various inputs")
    void testMultipleInputs(int input, int expected) {
        assertEquals(expected, instance.calculate(input));
    }
}
```

## Go Testing

### Go Test Template

```go
package mypackage

import (
    "testing"
)

func TestFunctionHappyPath(t *testing.T) {
    result := Function(validInput)
    expected := expectedOutput
    
    if result != expected {
        t.Errorf("Function(%v) = %v, want %v", validInput, result, expected)
    }
}

func TestFunctionEdgeCases(t *testing.T) {
    tests := []struct {
        name     string
        input    interface{}
        expected interface{}
        wantErr  bool
    }{
        {"empty input", "", "", false},
        {"nil input", nil, nil, true},
        {"zero value", 0, 0, false},
        {"negative value", -1, -1, false},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            result, err := Function(tt.input)
            
            if tt.wantErr && err == nil {
                t.Errorf("Function() expected error, got nil")
            }
            
            if !tt.wantErr && err != nil {
                t.Errorf("Function() unexpected error: %v", err)
            }
            
            if result != tt.expected {
                t.Errorf("Function() = %v, want %v", result, tt.expected)
            }
        })
    }
}

func BenchmarkFunction(b *testing.B) {
    for i := 0; i < b.N; i++ {
        Function(testInput)
    }
}
```

## Test Case Generation Strategy

### Step 1: Analyze Function Signature

```python
def analyze_function(func):
    """Analyze a function to suggest test cases"""
    import inspect
    
    sig = inspect.signature(func)
    suggestions = []
    
    for param_name, param in sig.parameters.items():
        # Check parameter type hints
        if param.annotation != inspect.Parameter.empty:
            suggestions.append(f"Test {param_name} with type {param.annotation}")
        
        # Check for default values
        if param.default != inspect.Parameter.empty:
            suggestions.append(f"Test {param_name} with default value {param.default}")
            suggestions.append(f"Test {param_name} with non-default value")
        
        # Suggest None test if no default
        else:
            suggestions.append(f"Test {param_name} with None value")
    
    return suggestions
```

### Step 2: Identify Test Scenarios

For any function, consider these test categories:

1. **Input Validation**
   - Valid inputs (happy path)
   - Invalid types
   - Out of range values
   - None/null values
   - Empty collections

2. **Business Logic**
   - Expected calculations
   - State changes
   - Side effects
   - Return values

3. **Error Handling**
   - Exception types
   - Error messages
   - Recovery behavior

4. **Integration Points**
   - Database interactions
   - API calls
   - File I/O
   - External dependencies

5. **Performance**
   - Large inputs
   - Concurrent access
   - Resource usage

### Step 3: Generate Test Cases

```python
def generate_test_cases(function_code):
    """
    Auto-generate test case suggestions from function code
    """
    import ast
    import re
    
    tree = ast.parse(function_code)
    test_cases = []
    
    for node in ast.walk(tree):
        # Detect conditionals -> suggest branch coverage
        if isinstance(node, ast.If):
            test_cases.append("Test both branches of conditional")
        
        # Detect loops -> suggest boundary tests
        if isinstance(node, (ast.For, ast.While)):
            test_cases.append("Test with 0 iterations")
            test_cases.append("Test with 1 iteration")
            test_cases.append("Test with multiple iterations")
        
        # Detect exception handling -> suggest error tests
        if isinstance(node, ast.Try):
            test_cases.append("Test exception path")
            test_cases.append("Test successful path without exception")
        
        # Detect assertions -> suggest violation tests
        if isinstance(node, ast.Assert):
            test_cases.append("Test assertion success")
            test_cases.append("Test assertion failure")
    
    return test_cases
```

## Test Data Generation

### Property-Based Testing

```python
# Using hypothesis for property-based testing
from hypothesis import given, strategies as st

@given(st.integers())
def test_property_always_positive(x):
    result = abs(x)
    assert result >= 0

@given(st.lists(st.integers(), min_size=1))
def test_list_operations(lst):
    sorted_list = sorted(lst)
    assert len(sorted_list) == len(lst)
    assert sorted_list[0] <= sorted_list[-1]
```

### Faker for Realistic Data

```python
from faker import Faker

fake = Faker()

def generate_test_user():
    return {
        "name": fake.name(),
        "email": fake.email(),
        "address": fake.address(),
        "phone": fake.phone_number(),
        "birthdate": fake.date_of_birth()
    }
```

## Test Quality Metrics

```bash
# Mutation testing (Python)
pip install mutpy
mut.py --target mymodule --unit-test tests/ --report-html report/

# Test complexity
pip install radon
radon cc tests/ -a

# Test smell detection
pip install pytest-testmon  # Only run tests affected by changes
pytest --testmon
```

## Tips for Writing Good Tests

1. **AAA Pattern**: Arrange, Act, Assert
2. **One assertion per test** (when practical)
3. **Descriptive test names** that explain what's being tested
4. **Independent tests**: No dependencies between tests
5. **Fast tests**: Mock slow operations
6. **Deterministic**: Same input always produces same output
7. **Readable**: Tests serve as documentation
8. **Maintainable**: Easy to update when code changes

## Test Naming Conventions

```
test_<function_name>_<scenario>_<expected_result>

Examples:
- test_calculate_sum_with_positive_numbers_returns_correct_total
- test_user_login_with_invalid_password_raises_authentication_error
- test_parse_json_with_empty_string_returns_none
```
