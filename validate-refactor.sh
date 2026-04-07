#!/bin/bash
# Refactor Validation Script
# Verifies all changes from correlation ID & topic configuration refactor

set -e

echo "=========================================="
echo "Correlation ID Refactor Validation"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

passed=0
failed=0

check_file() {
    if [ -f "$1" ]; then
        echo -e "${GREEN}✓${NC} File exists: $1"
        ((passed++))
    else
        echo -e "${RED}✗${NC} File missing: $1"
        ((failed++))
    fi
}

check_python() {
    if python3 -c "compile(open('$1').read(), '$1', 'exec')" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Python valid: $1"
        ((passed++))
    else
        echo -e "${RED}✗${NC} Python invalid: $1"
        ((failed++))
    fi
}

check_json() {
    if python3 -c "import json; json.load(open('$1'))" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} JSON valid: $1"
        ((passed++))
    else
        echo -e "${RED}✗${NC} JSON invalid: $1"
        ((failed++))
    fi
}

echo "Checking Python files..."
check_python "src/config/topic_config.py"
check_python "src/config/models.py"
check_python "src/config/loader.py"
check_python "src/test/loader.py"
check_python "src/test/suite.py"
check_python "src/test/logger.py"
echo ""

echo "Checking JSON schema files..."
check_json "topic-config-schema.json"
check_json "test-suite-schema.json"
check_json "rule-schema.json"
echo ""

echo "Checking YAML configuration files..."
check_file "config/topic-config/example-orders.yaml"
check_file "config/topic-config/example-users.yaml"
check_file "config/topic-config/example-payments.yaml"
echo ""

echo "Checking documentation files..."
check_file "docs/TOPIC_CONFIG.md"
check_file "docs/TEST_SUITE.md"
check_file "testSuite/examples/01-simple-injection.test.yaml"
echo ""

echo "Checking summary documents..."
check_file "REFACTOR_SUMMARY.md"
check_file "REFACTOR_CHECKLIST.md"
check_file "FILE_MANIFEST.md"
echo ""

echo "=========================================="
echo "Test Results: $passed passed, $failed failed"
echo "=========================================="
echo ""

if [ $failed -eq 0 ]; then
    echo -e "${GREEN}✓ All validations passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Review REFACTOR_SUMMARY.md for overview"
    echo "2. Read docs/TOPIC_CONFIG.md for configuration guide"
    echo "3. Update test YAML files to use new correlate format"
    echo "4. Validate with: check-jsonschema --schemafile topic-config-schema.json config/topic-config/*.yaml"
    echo ""
    exit 0
else
    echo -e "${RED}✗ Some validations failed!${NC}"
    echo "Please review the errors above."
    exit 1
fi

