# Topic Configuration Guide

Topic configurations define message format, schema registry settings, and correlation rules for each Kafka topic. This allows automatic correlation ID tracking across your system.

## Overview

Topic configurations are YAML files stored in `/config/topic-config/` (or subdirectories). Each file declares:
- **Message format** (json, avro, text, bytes) 
- **Schema Registry URL** (optional, overrides global)
- **Writer Schema ID** (for AVRO production)
- **Correlation extraction rules** (where to read correlation ID)
- **Correlation propagation rules** (where to write correlation ID)

Files are scanned **recursively** - organize by subdirectories as needed!

## Directory Structure

```
config/
├── topic-config/
│   ├── orders/
│   │   └── 01-orders.yaml
│   ├── payments/
│   │   └── 02-payments.yaml
│   └── notifications.yaml
└── rules/
    └── ...
```

**Multiple Topics Per File**: You can define multiple topic configurations in a single YAML file using the `---` separator (YAML document separator). This is useful for organizing related topics together:

```yaml
# payments-and-notifications.yaml
topic: payments.input
message:
  format: json
correlation:
  extract:
    - from: header
      name: X-Correlation-Id

---
# Second topic in same file
topic: notifications.events
message:
  format: json
```

Files are scanned **recursively** - organize by subdirectories as needed!

## Configuration Format

### Basic Structure

```yaml
topic: orders.input

# Message format and schema settings
message:
  format: json                               # json, avro, text, or bytes
  # schema_registry_url: http://localhost:8081  # Optional: override global
  # writer_schema_id: 123                       # Optional: for AVRO production

# Correlation tracking
correlation:
  extract:                                   # Where to read correlation ID (priority order)
    - from: header
      name: X-Correlation-Id
      priority: 1
    - from: jsonpath
      expression: $.correlationId
      priority: 2
  
  propagate:                                 # Where to write correlation ID when producing
    to_headers:
      X-Correlation-Id: "{{correlationId}}"
```

## Message Formats

### JSON
```yaml
topic: orders.input
message:
  format: json  # Default format
```

### AVRO
```yaml
topic: orders.events
message:
  format: avro
  schema_registry_url: http://localhost:8081  # Optional: overrides global
  writer_schema_id: 123                       # Schema ID for production
```

### Text or Bytes
```yaml
topic: raw.input
message:
  format: text    # or 'bytes'
```

## Correlation Configuration

### Extraction (Reading)

Specify where to extract correlation IDs from incoming messages. Rules are checked in priority order (lower number first).

```yaml
correlation:
  extract:
    - from: header
      name: X-Correlation-Id
      priority: 1
    - from: jsonpath
      expression: $.correlationId
      priority: 2
```

**From Header**:
- Looks for a specific Kafka message header
- Example: `X-Correlation-Id: "order-123"`

**From JSONPath**:
- Extracts value from JSON message body
- Example: `{"correlationId": "order-123", ...}`

### Propagation (Writing)

Optionally specify where to write correlation IDs when producing to this topic from rules or tests.

```yaml
correlation:
  propagate:
    to_headers:
      X-Correlation-Id: "{{correlationId}}"  # Use {{correlationId}} placeholder
```

When a rule produces a message to this topic:
- The correlation ID from the matched input message is automatically extracted
- Written to the specified header using the template

## Examples

### Example 1: Order Processing Topic

```yaml
# config/topic-config/orders.yaml
topic: orders.input

message:
  format: json

correlation:
  extract:
    - from: jsonpath
      expression: $.orderId
      priority: 1
    - from: header
      name: X-Order-Id
      priority: 2
  
  propagate:
    to_headers:
      X-Order-ID: "{{correlationId}}"
```

### Example 2: Payment Topic with AVRO

```yaml
# config/topic-config/payments.yaml
topic: payments.commands

message:
  format: avro
  schema_registry_url: http://schema-registry:8081
  writer_schema_id: 456

correlation:
  extract:
    - from: header
      name: X-Payment-Correlation-Id
      priority: 1
```

### Example 3: Multiple Topics in One File

```yaml
# config/topic-config/services.yaml
---
topic: users.commands
message:
  format: json
correlation:
  extract:
    - from: jsonpath
      expression: $.userId
      priority: 1

---
topic: users.events
message:
  format: json
correlation:
  extract:
    - from: jsonpath
      expression: $.userId
      priority: 1
```

## Integration with Rules

Rules automatically use topic-config settings:

```yaml
# config/rules/process-order.yaml
priority: 10

when:
  topic: orders.input           # Format/correlation rules from topic-config automatically applied
  match:
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CREATED"

then:
  - topic: payments.commands    # Correlation ID automatically propagated based on topic-config
    payload: |
      {
        "paymentId": "{{uuid}}",
        "orderId": "{{$.orderId}}"
      }
```

### Rule-Level Override

Override topic-config correlation rules for specific rules:

```yaml
priority: 10

when:
  topic: orders.input
  
  # Override correlation extraction for this rule
  correlation:
    extract:
      - from: jsonpath
        expression: $.customCorrelationId
        priority: 1

then:
  - topic: payments.commands
    
    # Override correlation propagation for this output
    correlation:
      to_headers:
        X-Custom-Correlation: "{{correlationId}}"
    
    payload: |
      {
        "paymentId": "{{uuid}}",
        "orderId": "{{$.orderId}}"
      }
```

## Integration with Tests

Tests use correlation configuration to automatically track message flow:

```yaml
# testSuite/examples/order-flow.test.yaml
priority: 10
name: "order-to-payment-flow"

when:
  inject:
    - message_id: "order1"
      topic: "orders.input"
      payload: |
        {
          "orderId": "{{testId}}-{{uuid}}",
          "userId": "USER-123"
        }

then:
  expectations:
    - topic: "payments.commands"
      wait_ms: 2000
      
      # Automatic correlation using topic-config
      correlate:
        message_id: "order1"
        source:
          jsonpath: "$.orderId"      # Extract from injected message
        target:
          jsonpath: "$.orderId"      # Match in received message
      
      match:
        - type: jsonpath
          expression: "$.status"
          value: "PENDING"
```

## Priority and Conflicts

**Topic-Config Priority**: 
1. Rule-level settings (highest priority)
2. Topic-config settings  
3. Global environment variables
4. Defaults

**Rule/Test Override Precedence**:
- If a header/field is already defined in rule/test, topic-config cannot override it
- Topic-config only fills in gaps
- Rule-level `correlation` block overrides topic-config `correlation`

## Schema Validation

Topic configs are validated against `topic-config-schema.json`. Place validation in your CI/CD pipeline:

```bash
# Using ajv-cli
ajv validate -s topic-config-schema.json -d "config/topic-config/**/*.yaml"
```

## Common Patterns

### Multi-Topic Correlation

Create a shared correlation format across multiple topics:

```yaml
# All user-related topics use userId
topic: user.commands
correlation:
  extract:
    - from: jsonpath
      expression: $.userId

---
topic: user.events
correlation:
  extract:
    - from: jsonpath
      expression: $.userId
```

### Header-Only Correlation

Some systems only propagate correlation via headers:

```yaml
topic: legacy.input
correlation:
  extract:
    - from: header
      name: correlation-id
  
  propagate:
    to_headers:
      correlation-id: "{{correlationId}}"
```

### No Correlation

Topics that don't need correlation tracking:

```yaml
topic: ping
message:
  format: text
# No correlation block needed
```

## Troubleshooting

### Correlation Not Found

If correlation IDs aren't being extracted:

1. Check topic-config exists in `/config/topic-config/`
2. Verify topic name matches exactly (case-sensitive)
3. Ensure JSONPath or header name is correct
4. Check message format matches what's declared

### Correlation Not Propagated

If output messages missing correlation headers:

1. Verify topic-config has `propagate` section
2. Check rule doesn't override correlation
3. Ensure incoming message has extractable correlation ID
4. Look for warnings in logs about extraction failures

## See Also

- [Rules Configuration](RULES.md) - Rule matching and outputs
- [Test Suite Guide](TEST_SUITE.md) - Testing with correlation
- Schema validation: `topic-config-schema.json`

