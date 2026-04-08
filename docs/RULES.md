# Rules Configuration Guide

Rules are the core of Kafka Wiremock. Each rule listens to an input topic, matches incoming messages with one or more conditions, and produces one or more output messages to other topics.

## Overview

- Rules are defined in **YAML files** inside `config/rules/` (or any subdirectory).
- Files are **scanned recursively** — organise by feature, team, or any structure that suits you.
- **Multiple rules per file**: separate documents with `---` (YAML multi-document).
- Rules are evaluated in **priority order** (lower number = higher priority). The **first matching rule wins**.
- Rules support **hot-reload**: changes are detected every few seconds with no container restart needed.

## Directory Structure

```
config/
└── rules/
    ├── order-processing/
    │   ├── 01-order-created.yaml
    │   └── 02-order-shipped.yaml
    ├── payments/
    │   ├── 05-payment-avro-output.yaml
    │   └── 06-payment-avro-input.yaml
    └── general/
        └── 03-placeholders.yaml
```

## Basic Rule Structure

```yaml
priority: 10              # Lower = higher priority (evaluated first)
name: "process-order"     # Optional human-readable name (defaults to filename)
skip: false               # Set to true to disable without deleting

when:
  topic: orders.input     # Input topic to listen on

  match:                  # Optional: list of conditions (ALL must match — AND logic)
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CREATED"

then:                     # List of output messages to produce
  - topic: payments.input
    delay_ms: 200
    payload: |
      {
        "paymentId": "{{uuid}}",
        "orderId": "{{$.orderId}}"
      }
```

## `when` Block

### `topic`

The Kafka topic the rule subscribes to. Required.

```yaml
when:
  topic: orders.input
```

### `match` Conditions (Optional)

If omitted, the rule acts as a **catch-all** for that topic.

All conditions in the list must match (**AND** logic). Supported condition types:

#### `jsonpath`

Extract a field from the JSON message body and compare it.

```yaml
- type: jsonpath
  expression: "$.eventType"   # JSONPath expression
  value: "ORDER_CREATED"      # Exact match (mutually exclusive with regex)

- type: jsonpath
  expression: "$.amount"
  regex: "[0-9]+"             # Regex match (mutually exclusive with value)
```

#### `exact`

The full message string must equal `value` exactly.

```yaml
- type: exact
  value: "ping"
```

#### `partial`

The full message string must contain `value` as a substring.

```yaml
- type: partial
  value: "ORDER_CREATED"
```

#### `regex`

The full message string must match the regular expression.

```yaml
- type: regex
  regex: "ORDER-\\d{4}"
```

#### `header`

Match a Kafka message header by name, with optional exact or regex value check.

```yaml
- type: header
  expression: "X-Correlation-ID"   # Header name
  value: "abc-123"                  # Exact match (optional)

- type: header
  expression: "my-test-header"
  regex: "^Header.*"               # Regex match (optional)
```

Omit both `value` and `regex` to check only for **header existence**.

#### `key`

Match the Kafka message key.

```yaml
- type: key
  value: "myMessageKey"    # Exact match

- type: key
  regex: "^CUST-.*"       # Regex match
```

Omit both to check only for **key existence**.

### Correlation Override (Optional)

Override the topic-config correlation extraction rules for this specific rule:

```yaml
when:
  topic: orders.input
  correlation:
    extract:
      - from: jsonpath
        expression: $.customCorrelationId
        priority: 1
```

See [TOPIC_CONFIG.md](TOPIC_CONFIG.md) for details.

---

## `then` Block

List of output messages to produce when the rule matches.

### Output Fields

| Field | Required | Description |
|-------|----------|-------------|
| `topic` | ✅ | Destination Kafka topic |
| `payload` | ✅* | Template string for the message body |
| `payload_file` | ✅* | Path to external payload template file (relative to rule file) |
| `delay_ms` | ❌ | Delay before producing (default: `0`) |
| `headers` | ❌ | Kafka headers as key-value map (values support templates) |
| `key` | ❌ | Message key (supports templates) |
| `schema_id` | ❌ | Confluent Schema Registry ID — serialises as AVRO |
| `correlation` | ❌ | Override correlation propagation for this output |
| `fault` | ❌ | Fault injection config (see below) |

*Exactly one of `payload` or `payload_file` is required.

### Template Placeholders

Use `{{ ... }}` syntax inside `payload`, `headers`, and `key` values.

| Placeholder | Description |
|-------------|-------------|
| `{{uuid}}` | Generate a new random UUID |
| `{{now}}` | Current UTC timestamp (ISO-8601) |
| `{{now+5m}}` / `{{now-1h}}` | Timestamp offset (supports `m`, `h`, `d`) |
| `{{randomInt(1,100)}}` | Random integer between 1 and 100 (inclusive) |
| `{{$.fieldName}}` | Extract a field from the matched input message |
| `{{$.nested.field}}` | Nested field extraction |
| `{{header.headerName}}` | Value of an input message header |
| `{{inputKey}}` | Message key of the input message |
| `{{full_message}}` | Full raw input message as a string |
| `{{correlationId}}` | Extracted correlation ID (from topic-config) |
| `{{testId}}` | (Tests only) Unique ID for the current test run |
| `{{myCustomPlaceholder}}` | Any custom placeholder loaded from `custom_placeholders/` |

### Multiple Outputs

A single rule can produce to multiple topics:

```yaml
then:
  - topic: payments.input
    delay_ms: 200
    payload: '{"paymentId": "{{uuid}}", "orderId": "{{$.orderId}}"}'

  - topic: notifications.events
    delay_ms: 100
    payload: '{"type": "ORDER_ACK", "orderId": "{{$.orderId}}"}'
```

### AVRO Output

Set `schema_id` to produce AVRO-encoded messages using the Confluent Schema Registry:

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

### Output Headers

```yaml
then:
  - topic: payments.input
    headers:
      X-Correlation-ID: "{{$.correlationId}}"
      X-Order-ID: "{{$.orderId}}"
      source: "order-service"
    payload: '{"paymentId": "{{uuid}}"}'
```

### Message Key

```yaml
then:
  - topic: users.events
    key: "{{$.userId}}"
    payload: '{"userId": "{{$.userId}}", "status": "PROCESSED"}'
```

### Execution Delay

```yaml
then:
  - topic: payments.input
    delay_ms: 500   # Wait 500ms before producing
    payload: '{"paymentId": "{{uuid}}"}'
```

### External Payload File

```yaml
then:
  - topic: payments.input
    payload_file: payloads/payment-created.json   # Relative to rule YAML file
```

---

## Fault Injection

Simulate realistic failure scenarios:

```yaml
then:
  - topic: payments.input
    payload: '{"paymentId": "{{uuid}}"}'
    fault:
      drop: 0.1              # 10% chance the message is dropped
      duplicate: 0.05        # 5% chance the message is sent twice
      poison_pill: 0.1       # 10% chance the message is corrupted
      random_latency: 0-500  # 0–500ms random additional delay
      poison_pill_type:      # Which corruption strategies to use (default: truncate)
        - truncate
        - invalid-json
        - corrupt-headers
        - messageKey
      check_result: false    # If false, test expectations are skipped for faulted messages
```

All probabilities are independent floats from 0.0 to 1.0.

---

## Skip Flag

Disable a rule without deleting it:

```yaml
skip: true
```

Useful during maintenance, gradual rollouts, or A/B testing.

---

## Multi-Document Files

Place multiple rules in one file using `---`:

```yaml
priority: 10
when:
  topic: orders.input
  match:
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CREATED"
then:
  - topic: payments.input
    payload: '{"paymentId": "{{uuid}}"}'

---

priority: 20
when:
  topic: orders.input
  match:
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CANCELLED"
then:
  - topic: notifications.events
    payload: '{"type": "ORDER_CANCELLED", "orderId": "{{$.orderId}}"}'
```

---

## Complete Example

```yaml
# config/rules/order-processing/01-order-created.yaml
priority: 10
name: "process-order-created"

when:
  topic: orders.input
  match:
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CREATED"
    - type: jsonpath
      expression: "$.amount"
      regex: "[0-9]+"

then:
  - topic: payments.input
    delay_ms: 200
    headers:
      correlationId: "{{$.correlationId}}"
      source: "order-service"
    payload: |
      {
        "paymentId": "{{uuid}}",
        "orderId": "{{$.orderId}}",
        "amount": "{{$.amount}}",
        "timestamp": "{{now}}",
        "correlationId": "{{$.correlationId}}"
      }

  - topic: notifications.events
    delay_ms: 100
    payload: |
      {
        "type": "ORDER_ACK",
        "orderId": "{{$.orderId}}",
        "notificationId": "{{uuid}}"
      }
```

---

## Schema Validation

Validate rule files against `rule-schema.json`:

```bash
# Using ajv-cli
ajv validate -s rule-schema.json -d "config/rules/**/*.yaml"
```

## See Also

- [Topic Configuration](TOPIC_CONFIG.md) — message format, correlation rules
- [Custom Placeholders](CUSTOM_PLACEHOLDERS.md) — user-defined placeholder functions
- [Test Suite](TEST_SUITE.md) — integration tests
- [API Reference](API.md) — HTTP endpoints
