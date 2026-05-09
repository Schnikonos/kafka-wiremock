# API Reference

Complete reference for all HTTP endpoints exposed by Kafka Wiremock.

## Base URL

By default the server listens on `http://localhost:8000`. Override with the `PORT` environment variable.

---

## Health

### `GET /health`

Returns service health status.

**Response**
```json
{ "status": "ok" }
```

---

## Message Injection & Consumption

### `POST /inject/{topic}`

Produce a message to a Kafka topic directly (bypasses rule matching — used for seeding tests or ad-hoc injection).

**Path params**
| Param | Description |
|-------|-------------|
| `topic` | Target Kafka topic |

**Headers (optional)**
| Header | Description |
|--------|-------------|
| `schema-id` | Confluent Schema Registry schema ID — serialises the payload as AVRO |

**Request body**
```json
{
  "message": { "orderId": "ORD-1", "amount": 99.99 }
}
```
`message` can be a JSON object, a JSON array, or a plain string.

**Response**
```json
{
  "message_id": "b3f2c1a0-...",
  "topic": "orders.input",
  "status": "success"
}
```

**Example**
```bash
curl -X POST http://localhost:8000/inject/orders.input \
  -H "Content-Type: application/json" \
  -d '{"message": {"orderId": "ORD-123", "amount": 99.99}}'
```

---

### `GET /messages/{topic}`

Consume messages from a Kafka topic using a short-lived consumer.

**Path params**
| Param | Description |
|-------|-------------|
| `topic` | Kafka topic to read from |

**Query params**
| Param | Default | Description |
|-------|---------|-------------|
| `limit` | `10` | Maximum messages to return (1–100) |
| `timeout_ms` | `500` | Total polling budget in milliseconds |
| `poll_interval_ms` | `100` | Duration of each individual poll call |

**Response** – array of message objects
```json
[
  {
    "topic": "payments.input",
    "partition": 0,
    "offset": 42,
    "key": null,
    "value": { "paymentId": "...", "amount": 99.99 },
    "headers": { "X-Correlation-ID": "abc-123" },
    "timestamp": 1712345678000
  }
]
```

**Example**
```bash
curl "http://localhost:8000/messages/payments.input?limit=5&timeout_ms=1000" | jq
```

---

## Rules

### `GET /rules`

List all loaded rules across all topics.

**Query params**
| Param | Default | Description |
|-------|---------|-------------|
| `errors` | `false` | Include YAML validation errors in the response |

**Response**
```json
{
  "rules": [
    {
      "name": "process-order",
      "priority": 10,
      "input_topic": "orders.input",
      "conditions": [...],
      "outputs": [...]
    }
  ]
}
```

---

### `GET /rules/{input_topic}`

List rules for a specific input topic.

**Example**
```bash
curl http://localhost:8000/rules/orders.input | jq
```

---

### `POST /rules:match`

Dry-run endpoint — shows which rule would match a given message and why, without producing any output.

**Query params**
| Param | Required | Description |
|-------|----------|-------------|
| `topic` | ✅ | Input topic |

**Request body** – the message payload (JSON object or string)

**Response**
```json
{
  "matched": true,
  "rule": { "name": "process-order", "priority": 10 },
  "conditions": [
    { "index": 0, "type": "jsonpath", "expression": "$.eventType", "value": "ORDER_CREATED", "matched": true }
  ],
  "context": { "$.eventType": "ORDER_CREATED", "$.orderId": "ORD-1" },
  "outputs_count": 2,
  "outputs": [{ "topic": "payments.input", "delay_ms": 200 }]
}
```

**Example**
```bash
curl -X POST "http://localhost:8000/rules:match?topic=orders.input" \
  -H "Content-Type: application/json" \
  -d '{"eventType": "ORDER_CREATED", "orderId": "ORD-1", "amount": 50}'
```

---

## Custom Placeholders

### `GET /custom-placeholders`

List all loaded custom placeholder functions with their execution order and docstrings.

**Response**
```json
[
  { "name": "discount",      "order": null, "docstring": "Calculate discount based on amount" },
  { "name": "final_price",   "order": null, "docstring": "Calculate final price after discount" },
  { "name": "tier_discount", "order": 20,   "docstring": "Calculate tier-based discount" }
]
```

---

## Python Dependencies

### `GET /dependencies`

Show the status of the background Python dependency manager (hot-installs `requirements.txt`).

**Response**
```json
{
  "status": "running",
  "requirements_file": "/config/python-requirements/requirements.txt",
  "requirements_exists": true,
  "log_file": "/config/python-requirements/requirements.log",
  "log_exists": true,
  "scan_interval_seconds": 30,
  "last_installation_log": "..."
}
```

---

## Tests

### `GET /tests`

List all discovered test definitions.

**Query params**
| Param | Default | Description |
|-------|---------|-------------|
| `errors` | `false` | Include YAML validation errors |

**Response**
```json
{
  "total": 3,
  "tests": [
    {
      "test_id": "simple-injection-test",
      "priority": 10,
      "tags": ["example", "basic"],
      "skip": false,
      "timeout_ms": 5000,
      "when_injections": 1,
      "then_expectations": 1
    }
  ]
}
```

---

### `GET /tests/{test_id}`

Get the full parsed definition of a single test.

**Response** – parsed test structure including injections, expectations, scripts, and correlation config.

---

### `POST /tests/{test_id}`

Run a single test synchronously (default) or asynchronously.

**Query params**
| Param | Default | Description |
|-------|---------|-------------|
| `async_mode` | `false` | If `true`, return immediately with a `job_id` |
| `verbose` | `false` | Include `received_messages` and `skipped_messages` in output |

**Synchronous response**
```json
{
  "test_id": "simple-injection-test",
  "status": "PASSED",
  "elapsed_ms": 312,
  "when_result": { "injected": true, "script_error": null },
  "then_result": {
    "expectations": [
      { "index": 0, "topic": "users.events", "status": "PASSED", "elapsed_ms": 210 }
    ],
    "script_error": null
  },
  "errors": []
}
```

**Async response (HTTP 200)**
```json
{
  "job_id": "job-abc123",
  "status": "RUNNING",
  "created_at": "2026-04-08T16:00:00Z",
  "message": "Test running asynchronously. Use GET /tests/jobs/{job_id} to poll status."
}
```

---

### `POST /tests:bulk`

Run multiple selected tests in bulk with repeat and parallel execution options.

**Request body**
```json
{
  "test_ids": ["test-1", "test-2"],
  "mode": "parallel",
  "repeat": 2,
  "parallel_workers": 4
}
```

**Parameters**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `test_ids` | string[] | _(required)_ | Array of test IDs to execute |
| `mode` | string | `parallel` | `sequential` or `parallel` |
| `repeat` | number | `1` | Number of times to repeat each test (1–1000) |
| `parallel_workers` | number | `4` | Concurrent workers for parallel mode (1–32) |

**Response**
```json
{
  "total": 4,
  "passed": 3,
  "failed": 1,
  "skipped": 0,
  "mode": "parallel",
  "repeat": 2,
  "elapsed_ms": 1523,
  "results": [
    { "test_id": "test-1", "status": "PASSED", "elapsed_ms": 312 },
    { "test_id": "test-2", "status": "FAILED", "elapsed_ms": 425 },
    { "test_id": "test-1", "status": "PASSED", "elapsed_ms": 298 },
    { "test_id": "test-2", "status": "FAILED", "elapsed_ms": 488 }
  ]
}
```

**Examples**
```bash
# Run 2 tests in parallel with 4 workers, repeat once
curl -X POST "http://localhost:8000/tests:bulk" \
  -H "Content-Type: application/json" \
  -d '{
    "test_ids": ["smoke-test", "integration-test"],
    "mode": "parallel",
    "repeat": 1,
    "parallel_workers": 4
  }'

# Run same 3 tests sequentially 5 times each (15 total executions)
curl -X POST "http://localhost:8000/tests:bulk" \
  -H "Content-Type: application/json" \
  -d '{
    "test_ids": ["test-1", "test-2", "test-3"],
    "mode": "sequential",
    "repeat": 5,
    "parallel_workers": 1
  }'
```

**Errors**
- `400` Bad Request – Invalid mode or parameters
- `404` Not Found – One or more test IDs don't exist
- `503` Service Unavailable – Test suite not initialized

---

### `POST /send:bulk`

Run multiple selected sends in bulk with repeat and parallel execution options.

**Request body**
```json
{
  "send_ids": ["send-order", "send-payment"],
  "mode": "parallel",
  "repeat": 1,
  "parallel_workers": 2
}
```

**Parameters**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `send_ids` | string[] | _(required)_ | Array of send IDs to execute |
| `mode` | string | `sequential` | `sequential` or `parallel` |
| `repeat` | number | `1` | Number of times to repeat each send (1–100) |
| `parallel_workers` | number | `4` | Concurrent workers for parallel mode (1–16) |

**Response**
```json
{
  "total": 2,
  "completed": 2,
  "failed": 0,
  "skipped": 0,
  "mode": "parallel",
  "repeat": 1,
  "elapsed_ms": 234,
  "results": [
    { "send_id": "send-order", "status": "COMPLETED", "elapsed_ms": 115 },
    { "send_id": "send-payment", "status": "COMPLETED", "elapsed_ms": 119 }
  ]
}
```

**Examples**
```bash
# Run 2 sends in parallel with 2 workers
curl -X POST "http://localhost:8000/send:bulk" \
  -H "Content-Type: application/json" \
  -d '{
    "send_ids": ["send-order", "send-payment"],
    "mode": "parallel",
    "repeat": 1,
    "parallel_workers": 2
  }'

# Run same send 10 times sequentially
curl -X POST "http://localhost:8000/send:bulk" \
  -H "Content-Type: application/json" \
  -d '{
    "send_ids": ["daily-sync"],
    "mode": "sequential",
    "repeat": 10,
    "parallel_workers": 1
  }'
```

**Errors**
- `400` Bad Request – Invalid mode or parameters
- `404` Not Found – One or more send IDs don't exist
- `503` Service Unavailable – Send executor not initialized

---

### `GET /tests/jobs`

List all async test jobs.

**Query params**
| Param | Description |
|-------|-------------|
| `test_id` | Filter by test ID (optional) |

**Response**
```json
{ "total": 2, "jobs": [ { "job_id": "...", "status": "COMPLETED", ... } ] }
```

---

### `GET /tests/jobs/{job_id}`

Poll the status of an async test job.

**Response** – job object with `status` (`RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`) and `result` when done.

---

### `GET /tests/logs`

List all `*.test.log` files written to `TEST_SUITE_DIR`.

---

### `GET /tests/logs/{test_id}`

Get the log file content for a specific test.

---

## Debug

These endpoints assist with development and troubleshooting. They do **not** produce Kafka messages.

### `POST /debug/decode`

Decode a raw message payload and show format detection details.

**Request body**
```json
{
  "topic": "payments.avro",
  "payload": "<base64-encoded-bytes-or-plain-string>"
}
```

**Response**
```json
{
  "success": true,
  "topic": "payments.avro",
  "expected_format": "avro",
  "detected_format": "avro",
  "decoded_value": { "paymentId": "...", "amount": 99.99 },
  "payload_size_bytes": 128,
  "schema_registry": { "cached_schemas": 1 }
}
```

---

### `POST /debug/match`

Test a message against rules and get a detailed per-condition analysis (useful for debugging why a rule does or doesn't match).

**Request body**
```json
{
  "topic": "orders.input",
  "payload": { "eventType": "ORDER_CREATED", "orderId": "ORD-1" },
  "rule_name": "process-order"
}
```
`rule_name` is optional — omit to test against all rules for the topic.

**Response**
```json
{
  "success": true,
  "topic": "orders.input",
  "total_rules": 3,
  "first_match": { "rule_name": "process-order", "matched": true, ... },
  "all_rules": [...]
}
```

---

### `GET /debug/topics`

Show all discovered topics with their type (json/avro/text/bytes), existence status, and consumer subscription state.

---

### `GET /debug/cache`

Show message cache statistics: entry count, TTL, consumption status.

---

### `POST /debug/template/render`

Render a template string with a provided context — useful for testing placeholder expressions before deploying rules.

**Request body**
```json
{
  "template": "{\"id\": \"{{uuid}}\", \"amount\": \"{{$.amount}}\", \"future\": \"{{now+5m}}\"}",
  "context": { "amount": 99.99 }
}
```

**Response**
```json
{
  "success": true,
  "template": "...",
  "rendered": "{\"id\": \"3fa85f64-...\", \"amount\": \"99.99\", \"future\": \"2026-04-08T16:05:00Z\"}",
  "placeholders_found": ["uuid", "$.amount", "now+5m"],
  "context_keys": ["amount"]
}
```
