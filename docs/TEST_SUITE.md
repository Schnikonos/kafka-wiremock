# Test Suite Guide

The Test Suite lets you define end-to-end integration tests that verify your Kafka event flows. Each test injects messages into Kafka and then checks that the expected output messages are produced.

## Overview

- Tests are defined in `*.test.yaml` files inside `testSuite/` (or any subdirectory).
- Files are scanned **recursively**.
- Tests run through the HTTP API: run one at a time or all at once.
- Hot-reload: new test files are detected automatically.

## Directory Structure

```
testSuite/
├── examples/
│   ├── 01-simple-injection.test.yaml
│   ├── 02-order-payment-flow.test.yaml
│   └── 03-multiple-conditions.test.yaml
└── your-feature/
    └── my-feature.test.yaml
```

---

## Test File Structure

```yaml
name: "my-test"           # Unique test identifier (required)
priority: 10              # Execution order — lower = runs first (default: 999)
tags: ["smoke", "orders"] # Tags for filtering (optional)
skip: false               # Set true to disable without deleting (default: false)
timeout_ms: 5000          # Overall test timeout in milliseconds (default: 5000)

when:
  inject:                 # Sequential list of injections and scripts

then:
  expectations:           # Sequential list of expectations and scripts
```

---

## `when` Block — Injections

### Message Injection

```yaml
when:
  inject:
    - message_id: "order1"        # Logical ID used in correlation (required)
      topic: "orders.input"       # Destination topic
      payload: |                  # Message body (supports template placeholders)
        {
          "orderId": "{{testId}}-{{uuid}}",
          "amount": 99.99,
          "eventType": "ORDER_CREATED"
        }
      headers:                    # Optional Kafka headers
        X-Correlation-ID: "{{uuid}}"
      key: "myKey"                # Optional message key (supports templates)
      delay_ms: 100               # Delay before injecting (default: 0)
      fault:                      # Optional fault injection (see Fault Injection below)
        drop: 0.1
```

#### Payload Templates

All [template placeholders](RULES.md#template-placeholders) are available in test injections, plus:

| Placeholder | Description |
|-------------|-------------|
| `{{testId}}` | Unique ID for this test run — use it to make message IDs unique across iterations |

#### External Payload File

```yaml
- message_id: "order1"
  topic: "orders.input"
  payload_file: payloads/order.json   # Path relative to the test YAML file
```

### Inline Script

Execute Python code between injections (or before/after all injections):

```yaml
when:
  inject:
    - message_id: "order1"
      topic: "orders.input"
      payload: '{"orderId": "ORD-1"}'

    - script: |
        # current_injection is bound to the most recently processed injection
        assert current_injection.get("payload", {}).get("orderId") == "ORD-1"
```

### Script File

```yaml
    - script_file: scripts/validate-order.py   # Relative to test file
```

---

## `then` Block — Expectations

Expectations are checked **in order**. Each waits up to `wait_ms` for a matching message to appear on the topic.

```yaml
then:
  expectations:
    - topic: "payments.input"
      wait_ms: 3000             # Maximum wait for this expectation (default: 2000)
      match:                    # Optional conditions (same types as in rules)
        - type: jsonpath
          expression: "$.amount"
          value: 99.99
        - type: header
          expression: "X-Correlation-ID"
          regex: "^[a-f0-9-]+$"
```

All [match condition types](RULES.md#match-conditions-optional) from rules are supported: `jsonpath`, `exact`, `partial`, `regex`, `header`, `key`.

### External Match File

```yaml
    - topic: "payments.input"
      match_file: expectations/payment-match.yaml   # Relative to test file
```

### Inline Script in `then`

```yaml
then:
  expectations:
    - topic: "payments.input"
      wait_ms: 3000

    - script: |
        # current_expectation.received_messages contains messages matched for the last expectation
        msg = current_expectation.received_messages[0] if current_expectation.received_messages else {}
        assert msg.get("value", {}).get("amount") == 99.99, f"Expected 99.99 but got {msg}"
```

---

## Correlation

Correlate an expected message back to a specific injected message by linking a field value:

```yaml
then:
  expectations:
    - topic: "payments.input"
      wait_ms: 3000
      correlate:
        message_id: "order1"          # Refers to the injection with this message_id
        source:
          jsonpath: "$.orderId"       # Extract this field from the injected message
        target:
          jsonpath: "$.orderId"       # Match it against this field in received messages
```

The correlation is **automatic** when you set only `message_id` and the topic-config defines extraction/propagation rules:

```yaml
      correlate:
        message_id: "order1"   # Simple: use topic-config correlation rules
```

You can also correlate via headers:

```yaml
      correlate:
        message_id: "order1"
        source:
          header: "X-Correlation-ID"   # Header from injected message
        target:
          header: "X-Correlation-ID"   # Header in expected message
```

---

## Fault Injection

Inject faults into test messages to verify your system's resilience:

```yaml
when:
  inject:
    - message_id: "order1"
      topic: "orders.input"
      payload: '{"orderId": "ORD-1"}'
      fault:
        drop: 0.2              # 20% chance message is dropped
        duplicate: 0.1         # 10% chance message is duplicated
        poison_pill: 0.1       # 10% chance message is corrupted
        random_latency: 0-200  # 0–200ms random latency
        poison_pill_type:
          - truncate
          - invalid-json
        check_result: false    # Skip expectations when fault applied (default: false)
```

When `check_result: false` (default), test expectations are automatically skipped for faulted messages so they don't cause false failures.

---

## Skip Flag

Disable a test without removing it:

```yaml
skip: true
```

---

## Running Tests

### List all tests

```bash
curl http://localhost:8000/tests | jq
```

### Run a single test (synchronous)

```bash
curl -X POST http://localhost:8000/tests/my-test | jq
```

### Run a single test (asynchronous)

```bash
# Start test, get job_id immediately
curl -X POST "http://localhost:8000/tests/my-test?async_mode=true"

# Poll job status
curl http://localhost:8000/tests/jobs/<job_id>
```

### Run all tests (parallel)

```bash
curl -X POST "http://localhost:8000/tests:bulk?mode=parallel&threads=8" | jq
```

### Run with tag filtering

```bash
curl -X POST "http://localhost:8000/tests:bulk?filter_tags=smoke&filter_tags=orders"
```

### Run with iterations (load / stability testing)

```bash
curl -X POST "http://localhost:8000/tests:bulk?iterations=50&mode=parallel&threads=16"
```

### Verbose output (include received messages in result)

```bash
curl -X POST "http://localhost:8000/tests/my-test?verbose=true" | jq
```

---

## Test Result Structure

```json
{
  "test_id": "simple-injection-test",
  "status": "PASSED",          // PASSED | FAILED | ERROR | SKIPPED
  "elapsed_ms": 312,
  "when_result": {
    "injected": true,
    "script_error": null
  },
  "then_result": {
    "expectations": [
      {
        "index": 0,
        "topic": "users.events",
        "expected": 1,
        "received": 1,
        "status": "PASSED",
        "elapsed_ms": 210,
        "error": null
      }
    ],
    "script_error": null
  },
  "errors": []
}
```

---

## Examples

### Example 1: Simple injection and validation

```yaml
# testSuite/examples/01-simple-injection.test.yaml
priority: 10
name: "simple-injection-test"
tags: ["example", "basic"]
timeout_ms: 5000

when:
  inject:
    - message_id: "order1"
      topic: "users.commands"
      headers:
        my-test-header: "HeaderValue123"
      key: "myMessageKey"
      payload: |
        {
          "action": "REGISTER",
          "username": "ABC",
          "email": "aaa@example.com",
          "source": "SomeSource",
          "amount": 99.99
        }

then:
  expectations:
    - topic: "users.events"
      wait_ms: 2000
      correlate:
        message_id: "order1"
      match:
        - type: key
          value: "myMessageKey"
        - type: header
          expression: "my-header"
          value: "MyCustomHeader"
        - type: jsonpath
          expression: "$.source"
          value: "SomeSource"
        - type: jsonpath
          expression: "$.status"
          regex: "PROCESSED|ACCEPTED"
```

### Example 2: Multi-step flow with scripts

```yaml
# testSuite/examples/02-order-payment-flow.test.yaml
priority: 20
name: "order-to-payment-flow"
tags: ["integration"]
timeout_ms: 8000

when:
  inject:
    - message_id: "order"
      topic: "orders.input"
      payload: |
        {
          "orderId": "ORD-{{testId}}-{{uuid}}",
          "amount": 150.50,
          "currency": "USD"
        }
    - script: |
        assert current_injection.get("payload", {}).get("currency") == "USD"

then:
  expectations:
    - source_id: "order"
      topic: "payments.input"
      target_id: "$.orderId"
      wait_ms: 3000
      match:
        - type: jsonpath
          expression: "$.amount"
          value: 150.50
    - script: |
        msg = current_expectation.received_messages[0] if current_expectation.received_messages else {}
        assert msg.get("value", {}).get("currency") == "USD"
```

---

## Schema Validation

Validate test files against `test-suite-schema.json`:

```bash
ajv validate -s test-suite-schema.json -d "testSuite/**/*.test.yaml"
```

---

## See Also

- [Rules Configuration](RULES.md) — matching strategies and output templates
- [Topic Configuration](TOPIC_CONFIG.md) — correlation rules
- [API Reference](API.md) — HTTP test endpoints
