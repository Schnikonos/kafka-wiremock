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

### Template Placeholders in `then` Expectations

`value` and `regex` fields inside any `match` condition are rendered as templates before the comparison is made. This means you can reference injected message fields, custom placeholders, built-in helpers, and the OR/fallback syntax inside `then` expectations — the same way you would in rule `then` payloads.

#### Available placeholders

| Placeholder | Description |
|-------------|-------------|
| `{{testId}}` | Name of the current test |
| `{{uuid}}` | Fresh random UUID |
| `{{now}}` / `{{now+5m}}` | Current UTC timestamp with optional offset |
| `{{inject.<message_id>.<field>}}` | Field from an injected `when` message, e.g. `{{inject.order1.orderId}}` |
| `{{myCustomPlaceholder}}` | Any custom placeholder defined in `custom_placeholders/` |

Script-accumulated `context` values (set in `when` or `then` scripts — see below) are also available as `{{myContextKey}}`.

#### OR / Fallback Syntax

Use pipe-separated alternatives, with an optional quoted literal as the final fallback:

```yaml
match:
  - type: jsonpath
    expression: "$.orderId"
    value: "{{inject.order1.orderId | inject.order1.id | \"DEFAULT\"}}"
```

Path traversal is **null-safe**: `{{inject.order1.a.b.c}}` returns `null` (not an error) when any intermediate key is absent.

#### Example — reference injected field in expectation

```yaml
when:
  inject:
    - message_id: "order1"
      topic: "orders.input"
      payload: |
        {"orderId": "{{uuid}}", "amount": 99.99}

then:
  expectations:
    - topic: "payments.output"
      wait_ms: 3000
      match:
        - type: jsonpath
          expression: "$.orderId"
          value: "{{inject.order1.orderId}}"   # must echo back the same orderId
        - type: jsonpath
          expression: "$.currency"
          value: "{{inject.order1.currency | \"EUR\"}}"   # fallback to EUR if absent
```

#### Numeric comparisons

Both `condition.value` and the actual extract are coerced to string before the final comparison when a placeholder is used. For purely static numeric values (no placeholder tokens), the original type is preserved.

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

## HTTP Stub Expectations

Use `type: http-stub` in the `then.expectations` list to register an HTTP stub **before** the
`when` injections run. The stub intercepts inbound HTTP requests to a mock server and waits for the
expected number of calls to arrive within the timeout window.

### How it works

1. Stubs are registered **before** `when.inject` fires — so any rule that makes an outbound HTTP
   call immediately hits the stub.
2. The test waits for the stub to receive `times` matching calls within `wait_ms` milliseconds.
3. Match conditions are evaluated against the **recorded call** (body, path params, etc.).
4. After the test (pass or fail) the stub is automatically removed from the cache.

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | ✅ | Must be `http-stub` |
| `server` | ✅* | Mock server name (required when >1 server is configured) |
| `path` | ✅ | Path pattern with optional `{param}` placeholders |
| `method` | ❌ | HTTP method filter (default `"*"` = any method) |
| `wait_ms` | ❌ | Timeout to wait for `times` calls (default `5000`) |
| `times` | ❌ | Expected number of calls (default `1`) |
| `match` | ❌ | Conditions evaluated against the recorded call |
| `response` | ❌ | HTTP response to return when the stub is hit |

#### `response` sub-fields

| Field | Default | Description |
|-------|---------|-------------|
| `status_code` | `200` | HTTP response status code |
| `payload` | `""` | Response body (template placeholders: `{{path.X}}` etc. resolved against incoming request) |
| `headers` | `{}` | Response headers map |
| `content_type` | `application/json` | `Content-Type` header value |

### Example

```yaml
# testSuite/payment-flow.test.yaml
name: payment-flow-test
when:
  inject:
    - topic: orders.input
      payload: |
        {
          "orderId": "ORDER-001",
          "amount": 99.99,
          "currency": "USD"
        }

then:
  expectations:
    # 1. Wait for the rule to POST to our mock payment API
    - type: http-stub
      server: payment-api
      path: /payments/{paymentId}
      method: POST
      wait_ms: 5000
      times: 1
      match:
        - type: jsonpath
          expression: "$.amount"
          value: 99.99
        - type: path_param
          expression: paymentId
          regex: "^PAY-.*"
      response:
        status_code: 201
        payload: |
          {
            "paymentId": "{{path.paymentId}}",
            "status": "ACCEPTED",
            "transactionId": "TXN-12345"
          }
        headers:
          Content-Type: application/json

    # 2. Kafka notification should arrive after the HTTP call
    - topic: notifications.events
      wait_ms: 3000
      match:
        - type: jsonpath
          expression: "$.type"
          value: "PAYMENT_ACCEPTED"
```

### Combined flow: Kafka → HTTP → Kafka

```
Kafka message (orders.input)
       ↓ rule matches
       ↓ rule POSTs to payment-api:8081/payments/{id}  ← stub responds with 201
       ↓ rule publishes to notifications.events
Test asserts: stub was called + Kafka message arrived
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
