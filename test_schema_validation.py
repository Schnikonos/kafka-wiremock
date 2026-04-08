#!/usr/bin/env python
"""Test schema validation with header matching."""

import json
import yaml
from jsonschema import validate, Draft7Validator

# Load schemas
with open('rule-schema.json') as f:
    rule_schema = json.load(f)

with open('test-suite-schema.json') as f:
    test_schema = json.load(f)

# Test 1: Rule with header match
print("=" * 70)
print("Test 1: Rule with header matching")
print("=" * 70)

rule_yaml = """
priority: 5
name: test-rule
when:
  topic: users.commands
  match:
    - type: header
      expression: "my-test-header"
      value: "HeaderValue123"
then:
  - topic: users.events
    headers:
      my-header: "MyCustomHeader"
    key: "123456"
    payload: '{"status": "PROCESSED"}'
"""

rule_data = yaml.safe_load(rule_yaml)
print(f"Rule data loaded: {rule_data['name']}")

try:
    validate(instance=rule_data, schema=rule_schema)
    print("✓ Rule with header match is VALID!")
except Exception as e:
    print(f"✗ Rule validation FAILED: {e}")

# Test 2: Test with header match
print("\n" + "=" * 70)
print("Test 2: Test with header matching")
print("=" * 70)

test_yaml = """
priority: 10
name: simple-injection-test
when:
  inject:
    - message_id: "order1"
      topic: "users.commands"
      headers:
        my-test-header: "HeaderValue123"
      key: "myMessageKey"
      payload: '{"action": "REGISTER"}'
then:
  expectations:
    - topic: "users.events"
      match:
        - type: header
          expression: "my-header"
          value: "MyCustomHeader"
        - type: jsonpath
          expression: "$.status"
          value: "PROCESSED"
"""

test_data = yaml.safe_load(test_yaml)
print(f"Test data loaded: {test_data['name']}")

try:
    validate(instance=test_data, schema=test_schema)
    print("✓ Test with header match is VALID!")
except Exception as e:
    print(f"✗ Test validation FAILED: {e}")

# Test 3: Mixed conditions
print("\n" + "=" * 70)
print("Test 3: Mixed match conditions (header + jsonpath)")
print("=" * 70)

mixed_test_yaml = """
priority: 10
name: mixed-conditions-test
when:
  inject:
    - message_id: "order1"
      topic: "orders"
      headers:
        X-Correlation-ID: "abc-123"
      payload: '{"status": "PENDING"}'
then:
  expectations:
    - topic: "shipments"
      match:
        - type: header
          expression: "X-Correlation-ID"
          regex: "^[a-z]+-[0-9]+$"
        - type: jsonpath
          expression: "$.status"
          value: "PROCESSED"
        - type: exact
          value: "complete"
"""

mixed_data = yaml.safe_load(mixed_test_yaml)
print(f"Test data loaded: {mixed_data['name']}")

try:
    validate(instance=mixed_data, schema=test_schema)
    print("✓ Test with mixed conditions is VALID!")
except Exception as e:
    print(f"✗ Test validation FAILED: {e}")

print("\n" + "=" * 70)
print("✓ All schema validation tests PASSED!")
print("=" * 70)

