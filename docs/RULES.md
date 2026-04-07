# Rules Configuration Guide

Rules define how Kafka Wiremock matches incoming messages and produces outputs. Configuration is stored in YAML files in the `/config/rules/` directory.

## Overview

Each rule file contains:
- **when**: Conditions to match incoming messages
- **then**: Output messages to produce
- **priority**: Order of evaluation (lower = higher priority)
- **name**: Friendly identifier for logging

## Directory Structure

```
config/
├── rules/
│   ├── order-processing/
│   │   ├── 01-order-created.yaml
│   │   └── 02-order-shipped.yaml
│   ├── payments/
│   │   └── 01-payment-confirmed.yaml
│   └── 01-catch-all.yaml
```

Files are scanned **recursively** - organize by subdirectories as your project grows!

## Rule Configuration Format

### Basic Structure

```yaml
priority: 10                           # Integer; lower = higher priority
name: "rule-name"                      # Friendly name for logging
skip: false                            # Optional; set to true to disable rule

when:
  topic: input-topic                   # Topic to listen to
  match:                               # Optional conditions (all ANDed)
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CREATED"           # Exact match or...
      regex: "[0-9]+"                  # Regex validation

then:                                  # List of output messages
  - topic: output-topic-1
    delay_ms: 200                      # Optional: latency simulation
    headers:                           # Optional: message headers
      X-Correlation-ID: "{{$.correlationId}}"
    schema_id: 123                     # Optional: AVRO schema ID
    payload: |
      {
        "paymentId": "{{uuid}}",
        "orderId": "{{$.orderId}}",
        "timestamp": "{{now}}"
      }
```

### Disabling Rules

Set `skip: true` to disable a rule without removing it:

```yaml
priority: 10
name: "disabled-rule"
skip: true              # This rule will not be evaluated

when:
  topic: orders
  # ...
then:
  # ...
```

This is useful for temporary disablement during testing or maintenance without deleting the rule configuration.

## Matching Strategies

### JSONPath Match (with optional regex)

Match JSON fields using JSONPath expressions with optional regex validation.

```yaml
when:
  topic: orders
  match:
    - type: jsonpath
      expression: "$.amount"
      value: "100.00"           # Exact match
    - type: jsonpath
      expression: "$.status"
      regex: "^(PENDING|APPROVED)$"  # Regex match
```

**Features**:
- Extract nested JSON fields
- Validate with exact value match or regex
- Multiple conditions are ANDed (all must match)

### Exact Match

```yaml
match:
  - type: exact
    value: "exact-string"
```

Matches only if the entire message equals the specified string.

### Partial Match

```yaml
match:
  - type: partial
    value: "substring"
```

Matches if the message contains the specified substring (case-sensitive).

### Regex Match

```yaml
match:
  - type: regex
    regex: "ORDER-\\d{4}"
```

Matches if the message matches the regex pattern. Capture groups are available in context.

## Output Configuration

### Multiple Outputs

A single rule can produce multiple messages to different topics:

```yaml
then:
  - topic: payments.input
    payload: |
      {
        "paymentId": "{{uuid}}",
        "orderId": "{{$.orderId}}"
      }
  
  - topic: notifications.input
    delay_ms: 500
    payload: |
      {
        "type": "ORDER_CREATED",
        "orderId": "{{$.orderId}}"
      }
```

### Message Headers

Add custom headers to output messages:

```yaml
then:
  - topic: output-topic
    headers:
      X-Correlation-ID: "{{$.correlationId}}"
      X-Order-ID: "{{$.orderId}}"
      Custom-Header: "static-value"
    payload: |
      {
        "status": "processed"
      }
```

Headers are rendered with the same template engine as payloads.

### Execution Delays

Simulate processing latency:

```yaml
then:
  - topic: output-topic
    delay_ms: 1000   # Wait 1 second before producing
    payload: '{"status": "completed"}'
```

### Fault Injection

Simulate failure scenarios by introducing faults to output messages:

```yaml
then:
  - topic: risky-topic
    payload: '{"status": "processing"}'
    fault:
      drop: 0.1                           # 10% chance message is dropped (not produced)
      duplicate: 0.05                     # 5% chance message is duplicated (sent twice)
      random_latency: "0-500"             # 0-500ms random delay
      poison_pill: 0.1                    # 10% chance message is corrupted
      poison_pill_type: ["truncate", "invalid-json"]  # Corruption types (optional)
```

**Fault Parameters**:
- `drop` (0.0-1.0): Probability message is dropped entirely (no output produced)
- `duplicate` (0.0-1.0): Probability message is produced twice
- `random_latency` (string): Range in milliseconds (format: "min-max", e.g., "0-100")
- `poison_pill` (0.0-1.0): Probability message payload is corrupted
- `poison_pill_type` (array): Corruption strategies: `truncate` (incomplete), `invalid-json`, `corrupt-headers`
- `check_result` (boolean): For test suites - if true, expectations validate faulted messages; if false, expectations are skipped (default: false)

## Template Placeholders

### Built-in Functions

- `{{uuid}}` - UUID v4
- `{{now}}` - Current UTC timestamp (ISO-8601)
- `{{now+5m}}`, `{{now-1h}}`, `{{now+1d}}` - Timestamp with offset
- `{{randomInt(1,100)}}` - Random integer

### Message Context

- `{{$.fieldName}}` - JSONPath extraction from message
- `{{message}}` - Full message as JSON object
- `{{full_message}}` - Message as string

### Custom Placeholders

Results from custom placeholder functions defined in `/config/custom_placeholders/`:

```yaml
payload: |
  {
    "discount": "{{discount}}",
    "finalPrice": "{{final_price}}"
  }
```

## AVRO Support

### Reading AVRO Messages

Messages are automatically deserialized from binary:

```yaml
when:
  topic: avro-input
  match:
    - type: jsonpath
      expression: "$.paymentId"
      value: "PAY-123"
```

### Producing AVRO Messages

Specify `schema_id` to produce AVRO:

```yaml
then:
  - topic: payments.avro
    schema_id: 123
    payload: |
      {
        "paymentId": "{{uuid}}",
        "orderId": "{{$.orderId}}"
      }
```

The payload is rendered as JSON, then AVRO-encoded using the schema registry.

## Real-World Examples

### Example 1: Order Processing

```yaml
priority: 10
name: "process-order"

when:
  topic: orders.input
  match:
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CREATED"

then:
  - topic: payments.input
    delay_ms: 200
    headers:
      X-Order-ID: "{{$.orderId}}"
    payload: |
      {
        "paymentId": "{{uuid}}",
        "orderId": "{{$.orderId}}",
        "amount": "{{$.amount}}",
        "timestamp": "{{now}}"
      }
```

### Example 2: Multiple Conditions

```yaml
priority: 15
name: "validate-transfer"

when:
  topic: transfers
  match:
    - type: jsonpath
      expression: "$.type"
      value: "TRANSFER"
    - type: jsonpath
      expression: "$.amount"
      regex: "^[0-9]{1,10}\\.[0-9]{2}$"
    - type: jsonpath
      expression: "$.status"
      value: "PENDING"

then:
  - topic: transfers.validated
    payload: |
      {
        "transferId": "{{uuid}}",
        "status": "VALIDATED",
        "processedAt": "{{now}}"
      }
```

### Example 3: Wildcard (Catch-all)

```yaml
priority: 999
name: "catch-all"

when:
  topic: dlq
  # No match block = matches any message

then:
  - topic: dlq.archive
    payload: '{"archived": true, "archivedAt": "{{now}}"}'
```

### Example 4: Fault Injection for Resilience Testing

```yaml
priority: 50
name: "risky-payment-processing"
skip: false

when:
  topic: payments.input
  match:
    - type: jsonpath
      expression: "$.type"
      value: "PAYMENT"

then:
  - topic: payments.processed
    delay_ms: 100
    payload: |
      {
        "paymentId": "{{$.paymentId}}",
        "status": "processed",
        "processedAt": "{{now}}"
      }
    fault:
      drop: 0.05                              # 5% chance payment is dropped (network failure)
      duplicate: 0.02                         # 2% chance payment is duplicated
      random_latency: "50-500"                # Random 50-500ms latency
      poison_pill: 0.03                       # 3% chance corrupted response
      poison_pill_type: ["truncate", "invalid-json"]
```

This rule simulates realistic failures: message loss (drop), duplicates, latency variations, and corrupted responses.

## Best Practices

1. **Use meaningful names** - Help team members understand rule purpose
2. **Set appropriate priorities** - 10 (critical), 50 (normal), 100 (low), 999 (catch-all)
3. **Test complex regex** - Validate regex patterns before deploying
4. **Use JSONPath** - More flexible than exact/partial matches for JSON messages
5. **Document context** - Add comments for complex matching logic
6. **Order rules logically** - Group related rules, specific before general

## Schema Validation

Use `rule-schema.json` in the project root to validate rule files:

```bash
# Single file
check-jsonschema --schemafile rule-schema.json config/rules/my-rule.yaml

# All rules
find config -name '*.yaml' -exec check-jsonschema --schemafile rule-schema.json {} +
```

## Hot-Reload

Rules are reloaded every 30 seconds. Changes are automatically picked up without restarting the service.

## See Also

- [Custom Placeholders Guide](CUSTOM_PLACEHOLDERS.md)
- [API Reference](API.md)

