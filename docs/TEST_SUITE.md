# Test Suite Guide

The Test Suite allows you to define comprehensive integration tests that verify your Kafka event flows end-to-end. Tests can inject messages, wait for expected outputs, validate using conditions, and execute custom Python scripts.

## Overview

Tests are defined in YAML files in `/testSuite/` directory with `*.test.yaml` extension. Each test:
- **Injects messages** to simulate upstream services
- **Waits for outputs** on specified topics
- **Validates messages** using matching conditions
- **Correlates** input and output via message IDs
- **Executes custom scripts** for setup and validation

## Directory Structure

```
testSuite/
├── examples/
│   ├── 01-simple-injection.test.yaml
│   ├── 02-order-payment-flow.test.yaml
│   └── 03-multiple-conditions.test.yaml
├── order-processing/
│   ├── 01-order-to-shipment.test.yaml
│   └── 02-order-to-payment.test.yaml
└── payments/
    └── 01-payment-confirmation.test.yaml
```

Files are scanned **recursively** - organize by subdirectories as your project grows!

## Test Definition Format

### Complete Example

```yaml
priority: 10                    # Optional; default 999. Lower = runs first
name: "order-to-payment-flow"   # Required; test identifier
tags: ["critical", "e2e"]       # Optional; for filtering
skip: false                     # Optional; skip test
timeout_ms: 5000               # Optional; overall test timeout

# INPUT PHASE: Inject messages
when:
  inject:
    - message_id: "order1"      # Correlation ID
      topic: "orders.input"     # Target topic
      payload: |
        {
          "orderId": "{{testId}}-{{uuid}}",
          "amount": 100.50,
          "status": "NEW"
        }
      headers:                  # Optional; custom headers
        X-Order-ID: "{{uuid}}"
      delay_ms: 100            # Optional; delay before injection
    
    - message_id: "notification"
      topic: "notifications.input"
      payload: '{"type": "order_created"}'
  
  script: |                     # Optional; Python setup code
    # Pre-conditions, assertions, custom logic
    assert len(injected) == 2, "Expected 2 injections"
    print(f"Setup phase: {len(injected)} messages injected")

# VALIDATION PHASE: Expect messages
then:
  expectations:
    - source_id: "order1"       # Optional; correlate to injected message
      target_id: "$.orderId"    # Field in received message to match source_id
      topic: "payments.input"   # Required; topic to consume from
      wait_ms: 2000            # Optional; timeout waiting for message (default 2000)
      match:                    # Optional; additional validation
        - type: jsonpath
          expression: "$.amount"
          value: 100.50
        - type: jsonpath
          expression: "$.status"
          regex: "PENDING|CONFIRMED"
    
    - source_id: "notification"
      target_id: "$.orderId"
      topic: "notifications.output"
      wait_ms: 3000
  
  script: |                     # Optional; custom validation code
    # Context has: injected[], received{}, stats{}
    payments = received.get("expectation_0", [])
    assert len(payments) == 1, f"Expected 1 payment, got {len(payments)}"
    print(f"✓ Validation passed: {len(payments)} payments received")
```

## When Block (Injection Phase)

The `when` block defines messages to inject and setup logic.

### Inject Messages

```yaml
when:
  inject:
    - message_id: "msg1"        # Unique ID for correlation
      topic: "orders"           # Kafka topic
      payload: |
        {
          "orderId": "ORD-123",
          "amount": 99.99
        }
      headers:                  # Optional
        X-Correlation-ID: "corr-123"
      delay_ms: 100            # Optional; milliseconds before injection
```

**Fields**:
- `message_id` (required): Unique identifier for this injection, used for correlation
- `topic` (required): Kafka topic to inject to
- `payload` (required): JSON or string message
- `headers` (optional): Custom message headers
- `delay_ms` (optional): Delay before injection (default: 0)
- `fault` (optional): Fault injection configuration (see below)

### Fault Injection in Test Injections

Simulate failure scenarios during test message injection:

```yaml
when:
  inject:
    - message_id: "order"
      topic: "orders"
      payload: |
        {
          "orderId": "ORD-{{testId}}-{{uuid}}",
          "amount": 100.50
        }
      fault:
        drop: 0.2                    # 20% chance message is dropped
        duplicate: 0.1               # 10% chance message is duplicated
        random_latency: "0-200"      # 0-200ms random delay
        poison_pill: 0.15            # 15% chance message is corrupted
        poison_pill_type: ["truncate", "invalid-json"]
        check_result: false          # Don't validate expectations for this injection
```

**Fault Parameters**:
- `drop` (0.0-1.0): Probability message is dropped (not produced at all)
- `duplicate` (0.0-1.0): Probability message is produced twice
- `random_latency` (string): Random delay range in ms (format: "min-max")
- `poison_pill` (0.0-1.0): Probability message payload is corrupted
- `poison_pill_type` (array): Corruption types: `truncate`, `invalid-json`, `corrupt-headers`
- `check_result` (boolean): If false (default), correlated expectations are automatically skipped when fault is applied. If true, expectations will still try to validate the faulted message.

When `check_result=false` and a fault is actually injected, any expectation correlated to that injection via `correlate.message_id` will be skipped with status `SKIPPED_DUE_TO_FAULT`.

### Template Placeholders in Injections

Use placeholders in injection payloads:

```yaml
inject:
  - message_id: "order"
    topic: "orders"
    payload: |
      {
        "orderId": "ORD-{{uuid}}",
        "timestamp": "{{now}}",
        "amount": {{randomInt(10,1000)}}
      }
```

Available:
- `{{uuid}}` - UUID v4
- `{{now}}` - Current timestamp
- `{{now+5m}}` - Timestamp with offset
- `{{randomInt(1,100)}}` - Random number
- `{{testId}}` - Unique test execution ID
- Message fields: `{{$.fieldName}}`

### Setup Script

Optional Python code for pre-conditions:

```yaml
when:
  inject: [...]
  
  script: |
    # Variables available:
    # - injected: List of injection results
    # - datetime: datetime module
    
    print(f"Injected {len(injected)} messages")
    assert len(injected) == 2, "Expected 2 messages"
    
    # Can use standard Python
    import json
    for msg in injected:
        print(json.dumps(msg, indent=2))
```

## Then Block (Validation Phase)

The `then` block defines expected outputs and validation logic.

### Expectations

Wait for and validate messages:

```yaml
then:
  expectations:
    - topic: "payments"         # Required; topic to consume from
      wait_ms: 5000            # Timeout (default: 2000)
      correlate:               # Optional; correlation configuration
        message_id: "order"    # Reference injected message_id
        source:
          jsonpath: "$.orderId"  # Extract from injected message
        target:
          jsonpath: "$.orderId"  # Match in received message
      match:                    # Optional; additional conditions
        - type: jsonpath
          expression: "$.amount"
          value: 100.50
```

**Fields**:
- `topic` (required): Topic to consume from
- `wait_ms` (optional): Timeout in milliseconds (default: 2000, max: 60000)
- `correlate` (optional): Message correlation configuration (see below)
- `match` (optional): Validation conditions (same as rule matching)

### Message Correlation

Use `correlate` block to verify message flow with correlation IDs:

```yaml
when:
  inject:
    - message_id: "order"
      topic: "orders"
      payload: |
        {
          "orderId": "ORD-{{uuid}}",
          "amount": 100.0
        }

then:
  expectations:
    - topic: "payments"
      correlate:
        message_id: "order"       # Reference injected message
        source:
          jsonpath: "$.orderId"   # Extract from injected message
        target:
          jsonpath: "$.orderId"   # Match in received message
```

**How it works**:
1. Injection creates: `{"orderId": "ORD-abc123", "amount": 100.0}`
2. Extract source value using jsonpath: `orderId = "ORD-abc123"`
3. Consume messages from `payments` topic
4. Find first message where target jsonpath matches: `$.orderId == "ORD-abc123"`

**Source/Target Types**:
- `jsonpath` - Extract from JSON message body
- `header` - Extract from Kafka message header

**Without Correlation**:

If no `correlate` block, any message matching conditions is accepted:

```yaml
expectations:
  - topic: "payments"
    match:
      - type: jsonpath
        expression: "$.status"
        value: "CONFIRMED"
```

**Manual Correlation ID Override**:

```yaml
when:
  inject:
    - message_id: "order1"
      topic: "orders"
      correlation_id: "my-custom-id"  # Override auto-generated
      payload: '{"orderId": "ORD-123"}'
```

### Validation Matching

Use the same matching strategies as rules:

```yaml
expectations:
  - topic: "payments"
    match:
      - type: jsonpath
        expression: "$.amount"
        value: 100.0
      - type: jsonpath
        expression: "$.status"
        regex: "^(PENDING|CONFIRMED)$"
      - type: regex
        regex: "PAY-\\d{5}"
```

Supported types:
- `jsonpath` - Match JSON fields
- `regex` - Match against full message
- `exact` - Exact match
- `partial` - Substring match

### Validation Script

Optional Python code for custom assertions:

```yaml
then:
  expectations: [...]
  
  script: |
    # Variables available:
    # - injected: List of injection results
    # - received: Dict mapping expectation index to messages
    # - stats: Test statistics
    
    # Validate injection results
    assert len(injected) == 1, "Should inject 1 message"
    
    # Validate received messages
    payments = received.get("expectation_0", [])
    assert len(payments) == 1, f"Expected 1 payment, got {len(payments)}"
    
    payment = payments[0]
    assert payment['value']['amount'] == 100.0
    assert payment['value']['status'] == 'CONFIRMED'
    
    print(f"✓ Test passed: {len(payments)} payments confirmed")
```

**Available context**:
- `injected` - Results from injection phase
- `received` - Dict: `expectation_index` → `[messages]`
- `stats` - Test statistics
- All Python builtins

## Test Metadata

```yaml
priority: 10                    # Lower = runs first (default: 999)
name: "my-test"                # Required; must be unique
tags: ["critical", "e2e"]      # Optional; for filtering
skip: false                    # Optional; skip this test
timeout_ms: 5000              # Optional; max test duration
```

**Tags** are used for filtering in bulk test runs:

```bash
curl -X POST "http://localhost:8000/tests:bulk?filter_tags=critical&filter_tags=e2e"
```

## API Endpoints

### List All Tests

```bash
GET /tests
```

Response:
```json
[
  {
    "test_id": "order-flow-test",
    "name": "order-to-payment-flow",
    "tags": ["critical", "e2e"],
    "priority": 10
  }
]
```

### Get Test Definition

```bash
GET /tests/{test_id}
```

Returns the parsed test YAML definition.

### Run Single Test

```bash
POST /tests/{test_id}
```

Response:
```json
{
  "test_id": "order-flow-test",
  "status": "PASSED",           // PASSED, FAILED, SKIPPED, TIMEOUT
  "elapsed_ms": 1234,
  "when_result": {
    "injected": [
      {"message_id": "order1", "topic": "orders", "status": "ok"}
    ],
    "script_error": null
  },
  "then_result": {
    "expectations": [
      {
        "index": 0,
        "topic": "payments",
        "expected": 1,
        "received": 1,
        "status": "MATCHED",
        "elapsed_ms": 145,
        "error": null
      }
    ],
    "script_error": null
  },
  "errors": []
}
```

### Run All Tests (Bulk)

```bash
POST /tests:bulk?mode=parallel&threads=4&iterations=10
```

**Query Parameters**:
- `mode`: `sequential` or `parallel` (default: `parallel`)
- `threads`: Number of concurrent threads, 1-32 (default: 4)
- `iterations`: Iterations per test, 1-1000 (default: 1)
- `filter_tags`: Tag names to filter (repeatable)

Response:
```json
{
  "mode": "parallel",
  "total_tests": 30,            // 3 tests × 10 iterations
  "passed": 28,
  "failed": 2,
  "skipped": 0,
  "duration_ms": 12345,
  "stats": {
    "order-flow-test": {
      "passed": 9,
      "failed": 1,
      "elapsed_ms_avg": 234.5,
      "elapsed_ms_max": 421,
      "elapsed_ms_min": 145
    }
  },
  "failed_tests": [
    {
      "test_id": "order-flow-test",
      "error": "Expectation failed: timeout waiting for message",
      "elapsed_ms": 2001
    }
  ]
}
```

## Real-World Examples

### Example 1: Simple Injection

```yaml
name: "simple-message-injection"
priority: 100

when:
  inject:
    - message_id: "test"
      topic: "orders"
      payload: '{"type": "test"}'

then:
  expectations:
    - source_id: "test"
      target_id: "$.type"
      topic: "processed"
      wait_ms: 1000
```

### Example 2: Order to Payment Flow

```yaml
name: "order-payment-flow"
priority: 10
tags: ["critical", "e2e"]

when:
  inject:
    - message_id: "order1"
      topic: "orders.input"
      payload: |
        {
          "orderId": "ORD-{{uuid}}",
          "customerId": "CUST-123",
          "amount": 150.00,
          "items": 2
        }
      delay_ms: 100
  
  script: |
    print(f"Injected {len(injected)} order messages")

then:
  expectations:
    - source_id: "order1"
      target_id: "$.orderId"
      topic: "payments.input"
      wait_ms: 3000
      match:
        - type: jsonpath
          expression: "$.amount"
          value: 150.00
        - type: jsonpath
          expression: "$.status"
          value: "PENDING"
    
    - source_id: "order1"
      target_id: "$.orderId"
      topic: "shipments.input"
      wait_ms: 3000
  
  script: |
    payments = received.get("expectation_0", [])
    shipments = received.get("expectation_1", [])
    
    assert len(payments) == 1, f"Expected 1 payment, got {len(payments)}"
    assert len(shipments) == 1, f"Expected 1 shipment, got {len(shipments)}"
    print("✓ Order successfully routed to payments and shipments")
```

### Example 3: Multi-Message Injection

```yaml
name: "complex-flow"
priority: 20
tags: ["integration"]

when:
  inject:
    - message_id: "order"
      topic: "orders"
      payload: |
        {
          "orderId": "ORD-{{uuid}}",
          "amount": 200.00
        }
    
    - message_id: "discount"
      topic: "promotions"
      payload: |
        {
          "discountCode": "SAVE10",
          "percentage": 10
        }
      delay_ms: 500

then:
  expectations:
    - topic: "orders.processed"
      wait_ms: 2000
    
    - topic: "discounts.applied"
      wait_ms: 2000
  
  script: |
    assert len(received.get("expectation_0", [])) == 1
    assert len(received.get("expectation_1", [])) == 1
```

## Best Practices

1. **Use meaningful test names** - Describe what flow is being tested
2. **Set priorities** - Critical tests first (lower priority number)
3. **Add tags** - Enable targeted test runs
4. **Use correlation** - Verify message flows end-to-end
5. **Set appropriate timeouts** - Account for processing delays
6. **Document expectations** - Add comments for complex flows
7. **Keep tests isolated** - Each test should be independent
8. **Use scripts for complex validation** - Python gives flexibility
9. **Test error cases** - Include negative test scenarios
10. **Bulk test regularly** - Catch regressions early

## Debugging Tests

### View Test Logs

```bash
docker-compose logs kafka-wiremock | grep -i "test_id"
```

### Run Single Test for Debugging

```bash
curl -X POST http://localhost:8000/tests/my-test
```

Check the detailed response for error messages in:
- `when_result.script_error`
- `then_result.script_error`
- `then_result.expectations[].error`

### Check Message Contents

Use `/messages/<topic>` endpoint to inspect what messages are on topics:

```bash
curl http://localhost:8000/messages/payments.input?limit=10
```

## Schema Validation

Test suite YAML files are validated against `test-suite-schema.json` in the project root. Use it to catch configuration errors early in your editor or CI pipeline.

### IDE Integration

#### VS Code

Install the [YAML extension by Red Hat](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml), then add the following to your `.vscode/settings.json`:

```json
{
  "yaml.schemas": {
    "./test-suite-schema.json": "testSuite/**/*.test.yaml"
  }
}
```

This enables in-editor validation, auto-complete, and hover documentation for all test files.

#### IntelliJ IDEA / PyCharm

1. Open **Settings** → **Languages & Frameworks** → **Schemas and DTDs** → **JSON Schema Mappings**
2. Click **+** to add a new mapping
3. Set **Schema file**: path to `test-suite-schema.json` in the project root
4. Set **File path pattern**: `testSuite/**/*.test.yaml`
5. Click **OK**

### Command-Line Validation

#### Using `check-jsonschema` (Python)

```bash
# Install
pip install check-jsonschema

# Validate a single test file
check-jsonschema --schemafile test-suite-schema.json testSuite/my-test.test.yaml

# Validate all test files
find testSuite -name '*.test.yaml' -exec check-jsonschema --schemafile test-suite-schema.json {} +
```

### CI/CD Integration

Add a validation step to your pipeline to prevent invalid tests from being deployed:

```yaml
# GitHub Actions example
- name: Validate test suite configuration
  run: |
    pip install check-jsonschema
    find testSuite -name '*.test.yaml' -exec check-jsonschema --schemafile test-suite-schema.json {} +
```

## See Also

- [Rules Configuration Guide](RULES.md)
- [API Reference](API.md)


