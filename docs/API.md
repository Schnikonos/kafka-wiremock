# API Reference

Complete documentation of Kafka Wiremock HTTP API endpoints.

## Base URL

```
http://localhost:8000
```

## Health & Info Endpoints

### Health Check

Check if the service is running and healthy.

```http
GET /health
```

**Response** (200 OK):
```json
{
  "status": "ok"
}
```

## Message Endpoints

### Inject Message

Inject a message into a Kafka topic.

```http
POST /inject/<topic>
Content-Type: application/json
schema-id: 123  # Optional header for AVRO schema ID

{
  "message": { "key": "value" } | "string"
}
```

**Parameters**:
- `<topic>` (path, required): Kafka topic name
- `schema-id` (header, optional): AVRO schema ID for producing AVRO format

**Request Body**:
- JSON object: `{ "key": "value" }`
- String: `"message content"`
- Nested objects and arrays supported

**Response** (200 OK):
```json
{
  "message_id": "orders-0-42",
  "topic": "orders",
  "status": "success"
}
```

**Response Fields**:
- `message_id`: Unique identifier (topic-partition-offset)
- `topic`: Kafka topic where message was injected
- `status`: "success" or error description

**Examples**:

```bash
# JSON message
curl -X POST http://localhost:8000/inject/orders \
  -H "Content-Type: application/json" \
  -d '{"orderId": "ORD-123", "amount": 99.99}'

# String message
curl -X POST http://localhost:8000/inject/events \
  -H "Content-Type: application/json" \
  -d '"event-type-1"'

# AVRO message (with schema ID)
curl -X POST http://localhost:8000/inject/payments \
  -H "Content-Type: application/json" \
  -H "schema-id: 5" \
  -d '{"paymentId": "PAY-123", "amount": 50.0}'
```

### Get Messages from Topic

Retrieve messages produced by Kafka Wiremock.

```http
GET /messages/<topic>?limit=10
```

**Parameters**:
- `<topic>` (path, required): Kafka topic name
- `limit` (query, optional): Number of messages to retrieve (1-100, default: 10)

**Response** (200 OK):
```json
[
  {
    "timestamp": 1704067200000,
    "partition": 0,
    "offset": 42,
    "key": "key123",
    "value": { "status": "ok" },
    "format": "json",
    "headers": { "X-Correlation-ID": "corr-123" }
  },
  {
    "timestamp": 1704067201000,
    "partition": 0,
    "offset": 43,
    "key": null,
    "value": { "paymentId": "uuid...", "orderId": "ORD-123" },
    "format": "avro",
    "headers": { "X-Order-ID": "ORD-123" }
  }
]
```

**Response Fields**:
- `timestamp`: Message timestamp (milliseconds)
- `partition`: Kafka partition number
- `offset`: Message offset in partition
- `key`: Message key (null if not set)
- `value`: Message value (JSON object or string)
- `format`: "json" or "avro"
- `headers`: Custom message headers (if any)

**Examples**:

```bash
# Get last 10 messages
curl http://localhost:8000/messages/orders

# Get last 50 messages
curl http://localhost:8000/messages/payments?limit=50

# Pretty print
curl http://localhost:8000/messages/events?limit=5 | jq
```

## Rules Endpoints

### List All Rules

Get all configured rules.

```http
GET /rules
```

**Response** (200 OK):
```json
[
  {
    "name": "order-to-shipment",
    "priority": 10,
    "input_topic": "orders",
    "match_strategy": "jsonpath",
    "outputs": [
      {
        "topic": "shipments",
        "delay_ms": 0,
        "template": "{\"status\": \"ok\"}"
      }
    ]
  }
]
```

**Response Fields**:
- `name`: Rule name
- `priority`: Execution priority (lower = higher priority)
- `input_topic`: Topic this rule listens to
- `match_strategy`: Type of matching used
- `outputs`: Array of output configurations

**Examples**:

```bash
# Get all rules
curl http://localhost:8000/rules

# Pretty print
curl http://localhost:8000/rules | jq

# Filter using jq
curl http://localhost:8000/rules | jq '.[] | select(.priority < 50)'
```

### List Rules for Specific Topic

Get rules that listen to a specific topic.

```http
GET /rules/<topic>
```

**Parameters**:
- `<topic>` (path, required): Kafka topic name

**Response** (200 OK):
Same format as `/rules` but filtered for the topic.

**Examples**:

```bash
# Get rules for orders topic
curl http://localhost:8000/rules/orders

# Get rules for payments topic
curl http://localhost:8000/rules/payments | jq
```

## Custom Placeholders Endpoint

### List Custom Placeholders

Get all registered custom placeholder functions.

```http
GET /custom-placeholders
```

**Response** (200 OK):
```json
[
  {
    "name": "discount",
    "order": null,
    "file": "10-business_logic.py"
  },
  {
    "name": "final_price",
    "order": 10,
    "file": "20-calculations.py"
  },
  {
    "name": "total_with_tax",
    "order": 20,
    "file": "20-calculations.py"
  }
]
```

**Response Fields**:
- `name`: Placeholder function name
- `order`: Execution order (null = unordered, executes first)
- `file`: Python file where placeholder is defined

**Examples**:

```bash
# List all placeholders
curl http://localhost:8000/custom-placeholders

# Pretty print
curl http://localhost:8000/custom-placeholders | jq

# Filter by order
curl http://localhost:8000/custom-placeholders | jq '.[] | select(.order != null)'
```

## Test Suite Endpoints

### List All Tests

Get all discovered test definitions.

```http
GET /tests
```

**Response** (200 OK):
```json
[
  {
    "test_id": "order-flow-test",
    "name": "order-to-payment-flow",
    "tags": ["critical", "e2e"],
    "priority": 10,
    "skip": false
  }
]
```

**Response Fields**:
- `test_id`: Unique test identifier
- `name`: Friendly test name
- `tags`: Associated tags
- `priority`: Execution priority
- `skip`: Whether test is skipped

**Examples**:

```bash
# List all tests
curl http://localhost:8000/tests

# Pretty print
curl http://localhost:8000/tests | jq

# Filter critical tests
curl http://localhost:8000/tests | jq '.[] | select(.tags[] == "critical")'
```

### Get Test Definition

Get the parsed YAML definition of a test.

```http
GET /tests/{test_id}
```

**Parameters**:
- `{test_id}` (path, required): Test identifier

**Response** (200 OK):
```json
{
  "test_id": "order-flow-test",
  "name": "order-to-payment-flow",
  "priority": 10,
  "tags": ["critical", "e2e"],
  "skip": false,
  "timeout_ms": 5000,
  "when": {
    "inject": [...],
    "script": "..."
  },
  "then": {
    "expectations": [...],
    "script": "..."
  }
}
```

**Examples**:

```bash
# Get test definition
curl http://localhost:8000/tests/order-flow-test

# Pretty print
curl http://localhost:8000/tests/order-flow-test | jq
```

### Run Single Test

Execute a single test and get results.

```http
POST /tests/{test_id}
```

**Parameters**:
- `{test_id}` (path, required): Test identifier

**Response** (200 OK):
```json
{
  "test_id": "order-flow-test",
  "status": "PASSED",
  "elapsed_ms": 1234,
  "when_result": {
    "injected": [
      {
        "message_id": "order1",
        "topic": "orders",
        "status": "ok"
      }
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

**Response Fields**:
- `test_id`: Test identifier
- `status`: "PASSED", "FAILED", "SKIPPED", or "TIMEOUT"
- `elapsed_ms`: Execution time
- `when_result`: Injection phase results
- `then_result`: Validation phase results
- `errors`: Array of error messages (if any)

**Examples**:

```bash
# Run test
curl -X POST http://localhost:8000/tests/order-flow-test

# Pretty print
curl -X POST http://localhost:8000/tests/order-flow-test | jq

# Check status only
curl -X POST http://localhost:8000/tests/order-flow-test | jq '.status'
```

### Run All Tests (Bulk)

Execute all tests in parallel or sequential mode.

```http
POST /tests:bulk?mode=parallel&threads=4&iterations=10&filter_tags=critical
```

**Query Parameters**:
- `mode` (optional): "sequential" or "parallel" (default: "parallel")
- `threads` (optional): Number of concurrent threads, 1-32 (default: 4)
- `iterations` (optional): Iterations per test, 1-1000 (default: 1)
- `filter_tags` (optional, repeatable): Tag names to filter

**Response** (200 OK):
```json
{
  "mode": "parallel",
  "total_tests": 30,
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
      "iteration": 5,
      "error": "Expectation failed: timeout waiting for message",
      "elapsed_ms": 2001
    }
  ]
}
```

**Response Fields**:
- `mode`: Execution mode
- `total_tests`: Number of test executions (tests × iterations)
- `passed`: Number of passed tests
- `failed`: Number of failed tests
- `skipped`: Number of skipped tests
- `duration_ms`: Total execution time
- `stats`: Per-test statistics
- `failed_tests`: Details of failed tests

**Examples**:

```bash
# Run all tests in parallel with 4 threads
curl -X POST "http://localhost:8000/tests:bulk"

# Run tests sequentially
curl -X POST "http://localhost:8000/tests:bulk?mode=sequential"

# Run 10 iterations with 8 threads
curl -X POST "http://localhost:8000/tests:bulk?iterations=10&threads=8"

# Run only critical tests
curl -X POST "http://localhost:8000/tests:bulk?filter_tags=critical"

# Run multiple tags (OR condition)
curl -X POST "http://localhost:8000/tests:bulk?filter_tags=critical&filter_tags=e2e"

# Pretty print
curl -X POST "http://localhost:8000/tests:bulk" | jq
```

## Error Responses

### 400 Bad Request

Invalid parameters or payload.

```json
{
  "detail": "Invalid topic name"
}
```

### 404 Not Found

Resource not found.

```json
{
  "detail": "Test 'unknown-test' not found"
}
```

### 500 Internal Server Error

Server error.

```json
{
  "detail": "Internal server error"
}
```

## Common Patterns

### Monitor Rule Execution

```bash
# 1. List rules
curl http://localhost:8000/rules | jq '.[] | {name, input_topic}'

# 2. Inject test message
curl -X POST http://localhost:8000/inject/orders \
  -H "Content-Type: application/json" \
  -d '{"test": "message"}'

# 3. Check output topic
curl http://localhost:8000/messages/payments?limit=5 | jq
```

### Test Custom Placeholder

```bash
# 1. Check placeholder registered
curl http://localhost:8000/custom-placeholders | jq '.[] | select(.name == "my_placeholder")'

# 2. Inject message that uses it
curl -X POST http://localhost:8000/inject/test \
  -d '{"value": 100}'

# 3. Check output
curl http://localhost:8000/messages/output | jq '.[0].value'
```

### Bulk Testing with Monitoring

```bash
# Run tests and save results
curl -X POST "http://localhost:8000/tests:bulk?mode=parallel&iterations=5" > results.json

# Check summary
jq '{mode, total_tests, passed, failed, duration_ms}' results.json

# Analyze failures
jq '.failed_tests[] | {test_id, error}' results.json
```

## Integration Examples

### cURL

```bash
# Simple health check
curl http://localhost:8000/health

# With error handling
curl -s http://localhost:8000/health || echo "Service down"
```

### Python

```python
import requests
import json

# Get messages
response = requests.get('http://localhost:8000/messages/orders?limit=10')
messages = response.json()
print(json.dumps(messages, indent=2))

# Inject message
response = requests.post(
    'http://localhost:8000/inject/orders',
    json={"orderId": "ORD-123", "amount": 99.99}
)
print(response.json())

# Run test
response = requests.post('http://localhost:8000/tests/my-test')
test_result = response.json()
print(f"Test status: {test_result['status']}")
```

### JavaScript

```javascript
// Get rules
fetch('http://localhost:8000/rules')
  .then(r => r.json())
  .then(rules => console.log(rules));

// Inject message
fetch('http://localhost:8000/inject/orders', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({orderId: 'ORD-123', amount: 99.99})
})
.then(r => r.json())
.then(result => console.log(result));
```

## See Also

- [Rules Configuration Guide](RULES.md)
- [Test Suite Guide](TEST_SUITE.md)
- [Custom Placeholders Guide](CUSTOM_PLACEHOLDERS.md)

