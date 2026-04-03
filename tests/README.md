# Unit Tests for kafka-wiremock

This directory contains comprehensive unit tests for the kafka-wiremock project.

## Test Files

### `test_custom_placeholders.py` (40+ tests)
Tests for the custom placeholder system:
- **Decorators**: `@placeholder`, `@order(priority)`
- **Loading**: From PLACEHOLDERS dict, from decorator, multiple files
- **Execution Order**: Unordered first, then by priority
- **Pipeline**: Context building and passing between placeholders
- **Calculations**: Real-world calculation scenarios  
- **Error Handling**: Missing values, exceptions, type conversions
- **Hot-Reload**: File add/modify/delete detection

Key test classes:
- `TestPlaceholderDecorators` - Decorator functionality
- `TestPlaceholderLoading` - Loading from files
- `TestPlaceholderOrdering` - Execution order
- `TestPipelineExecution` - Pipeline context flow
- `TestCalculationPlaceholders` - Real calculation scenarios
- `TestErrorHandling` - Error cases
- `TestPlaceholderFileChanges` - Hot-reload detection

### `test_config_loader.py` (40+ tests)
Tests for YAML configuration loading:
- **Parsing**: Simple/complex rules, multiple conditions, multiple outputs
- **Loading**: Multiple files, nested subdirectories, topic indexing
- **Hot-Reload**: File add/modify/delete detection
- **Validation**: Required fields, invalid types
- **Condition Types**: jsonpath, exact, partial, regex

Key test classes:
- `TestConfigParsing` - YAML parsing
- `TestConfigLoading` - Multi-file loading
- `TestConfigHotReload` - Change detection
- `TestConfigValidation` - Error validation
- `TestConditionTypes` - All match types

### `test_matcher.py` (30+ tests)
Tests for all matching strategies:
- **JSONPath**: Simple/nested paths, regex validation, extraction
- **Exact**: String matching, case sensitivity
- **Partial**: Substring matching
- **Regex**: Pattern matching, groups, complex patterns
- **Factory**: Matcher creation and caching
- **Complex**: Multiple conditions, arrays, decimals

Key test classes:
- `TestJSONPathMatcher` - JSONPath matching
- `TestExactMatcher` - Exact matching
- `TestPartialMatcher` - Substring matching
- `TestRegexMatcher` - Regular expressions
- `TestMatcherFactory` - Factory pattern
- `TestComplexMatching` - Complex scenarios

### `test_templater.py` (50+ tests)
Tests for template rendering and placeholders:
- **Built-in**: uuid, now, now±offset, randomInt
- **Context**: Variable substitution, JSONPath access
- **Default Values**: {{field : default}} syntax
- **Complex**: JSON, multiline, nested templates
- **Missing**: Handling undefined values
- **Types**: Numbers, booleans, lists, dicts

Key test classes:
- `TestBuiltInPlaceholders` - Built-in functions
- `TestContextPlaceholders` - Variable substitution
- `TestDefaultValues` - Default value syntax
- `TestComplexTemplates` - Complex scenarios
- `TestMissingPlaceholders` - Error handling
- `TestTypeHandling` - Type conversions
- `TestEdgeCases` - Edge cases

## Running Tests

### Run All Tests
```bash
python3 -m unittest discover tests -v
```

### Run Specific Test Module
```bash
python3 -m unittest tests.test_templater -v
python3 -m unittest tests.test_custom_placeholders -v
python3 -m unittest tests.test_config_loader -v
python3 -m unittest tests.test_matcher -v
```

### Run Specific Test Class
```bash
python3 -m unittest tests.test_templater.TestBuiltInPlaceholders -v
```

### Run Specific Test
```bash
python3 -m unittest tests.test_templater.TestBuiltInPlaceholders.test_uuid_placeholder -v
```

### Using pytest (if installed)
```bash
pytest tests/ -v
pytest tests/test_templater.py -v
pytest tests/test_templater.py::TestBuiltInPlaceholders::test_uuid_placeholder -v
```

### Using the Test Runner Script
```bash
# Run all tests
python3 run_tests.py

# Run specific module
python3 run_tests.py --test templater

# Verbose output
python3 run_tests.py --verbose
```

## Test Coverage

| Component | Coverage | Tests |
|-----------|----------|-------|
| Custom Placeholders | High | 40+ |
| Config Loader | High | 40+ |
| Matcher | High | 30+ |
| Templater | High | 50+ |
| **Total** | **High** | **160+** |

## Key Test Scenarios

### Custom Placeholders
✅ Decorator functionality (`@placeholder`, `@order`)
✅ Loading from multiple sources (dict, decorators)
✅ Execution order (unordered first, then by priority)
✅ Context passing between placeholders
✅ Cascading calculations
✅ Hot-reload file detection

### Configuration Loading  
✅ Simple and complex rule parsing
✅ Multiple AND conditions
✅ Multiple output messages
✅ Wildcard rules (no conditions)
✅ Subdirectory support
✅ Topic indexing
✅ Hot-reload detection

### Matching
✅ JSONPath matching with extraction
✅ Exact string matching
✅ Partial/substring matching
✅ Regex pattern matching
✅ Multiple conditions (AND logic)
✅ Complex nested structures

### Templating
✅ Built-in functions (uuid, now, randomInt)
✅ Time offsets (now+5m, now-1h, now+1d)
✅ Context variable substitution
✅ JSONPath style access ($.field)
✅ Default values ({{field : default}})
✅ Type conversions
✅ Complex JSON templates

## Writing New Tests

Each test file follows standard unittest structure:

```python
import unittest
from src.module import Component

class TestComponentFeature(unittest.TestCase):
    """Test description."""
    
    def test_specific_behavior(self):
        """Test description."""
        # Arrange
        input_data = ...
        expected = ...
        
        # Act
        result = Component.method(input_data)
        
        # Assert
        self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()
```

## Best Practices

1. **Test Names**: Start with `test_` and be descriptive
2. **Docstrings**: Always include docstrings explaining what is tested
3. **Arrange-Act-Assert**: Follow AAA pattern
4. **Isolation**: Each test should be independent
5. **Mocking**: Use tempfile for I/O tests
6. **Coverage**: Aim for 80%+ coverage of important code paths

## Continuous Integration

Tests can be integrated into CI/CD pipelines:

```bash
# In GitHub Actions or similar
python3 -m unittest discover tests -v
```

## Troubleshooting

### Import Errors
Ensure you're running from the project root directory:
```bash
cd /path/to/kafka-wiremock
python3 -m unittest discover tests -v
```

### Missing Dependencies
Install dependencies:
```bash
pip install -r requirements.txt
```

### venv Issues
Activate the virtual environment:
```bash
source .venv/bin/activate
```

## Contributing

When adding new features:
1. Write tests first (TDD recommended)
2. Ensure all existing tests pass
3. Add tests for edge cases and error conditions
4. Keep test names descriptive
5. Maintain test isolation

