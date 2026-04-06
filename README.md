# Kafka Wiremock

Event-driven Kafka mock container for testing, similar to Pact for APIs. Intercepts messages on Kafka topics, applies configurable matching rules, and produces replies with templated responses.

## Features

- **Multiple Matching Strategies**: Exact match, partial match, regex, JSONPath with optional regex validation
- **Rich Templating**: UUID, timestamps with offsets, random data, JSONPath extraction
- **Custom Placeholders**: User-defined placeholder functions with ordered pipeline execution
- **Multiple Outputs**: Single rule can produce multiple messages to different topics  
- **Message Headers**: Add correlation IDs and custom headers to outputs
- **Execution Delays**: Simulate processing latency with `delay_ms`
- **AVRO Support**: 
  - Read AVRO messages from topics (decoded to JSON for display)
  - Match against AVRO messages using JSONPath
  - Produce AVRO messages with schema registry IDs
- **Test Suite** (NEW): 
  - Define integration tests with `when` (inject) → `then` (validate) structure
  - Message correlation via source_id/target_id
  - Custom Python scripts for setup and validation
  - Sequential or parallel test execution
  - Bulk testing with statistics (average/max elapsed time)
- **Hot-Reload Configuration**: Configuration files reloaded every 30 seconds
- **HTTP API**: 
  - `POST /inject/<topic>` - Inject test messages (JSON/AVRO with schema-id header)
  - `GET /messages/<topic>` - Retrieve produced messages (JSON/AVRO decoded)
  - `GET /custom-placeholders` - List custom placeholders
  - `GET /tests` - List all test definitions
  - `POST /tests/<test_id>` - Run single test
  - `POST /tests:bulk` - Run all tests (sequential/parallel)
  - `GET /health` - Health check
  - `GET /rules` - List all configured rules
  - `GET /rules/<topic>` - List rules for specific topic
- **Docker Ready**: Lightweight Python container with all dependencies

## Quick Start

### 1. Using Docker Compose

```bash
# Start all services (Kafka + Zookeeper + Kafka Wiremock)
docker-compose up -d

# Check if Kafka Wiremock is healthy
curl http://localhost:8000/health
```

### 2. Inject a Test Message

```bash
curl -X POST http://localhost:8000/inject/orders \
  -H "Content-Type: application/json" \
  -d '{"message": "order-created"}'
```

### 3. Check Produced Messages

```bash
curl http://localhost:8000/messages/shipments?limit=10
```

### 4. View Configured Rules

```bash
curl http://localhost:8000/rules
```

## Configuration

Configuration is stored in YAML files in the `/config` directory (one rule per file). Files are loaded recursively from any subdirectory, with rules evaluated by priority (lower number = higher priority).

### Directory Structure

```
config/
├── rules/                          # Optional: organize rules in subdirectories
│   ├── order-processing/
│   │   ├── 01-order-created.yaml
│   │   └── 02-order-shipped.yaml
│   ├── payments/
│   │   └── 01-payment-confirmed.yaml
│   └── 01-catch-all.yaml           # Also works at top level
└── custom_placeholders/            # Custom placeholder functions
    ├── business/
    │   └── 10-discounts.py
    ├── integrations/
    │   └── 20-external-apis.py
    └── 10-business_logic.py         # Also works at top level
```

**Both files are scanned recursively** - organize by subdirectories as your project grows!

### Rule Configuration Format

```yaml
priority: 10                           # Integer; lower = higher priority
name: "rule-name"                      # Friendly name for logging

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

### Template Placeholders

**Built-in Functions**:
- `{{uuid}}` - UUID v4
- `{{now}}` - Current UTC timestamp (ISO-8601)
- `{{now+5m}}`, `{{now-1h}}`, `{{now+1d}}` - Timestamp with offset
- `{{randomInt(1,100)}}` - Random integer

**Message Context**:
- `{{$.fieldName}}` - JSONPath extraction
- `{{message}}` - Full message object
- `{{full_message}}` - Message as string

### Matching Strategies

#### JSONPath Match (with optional regex)
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

#### Exact/Partial/Regex Matches

```yaml
match:
  - type: exact
    value: "exact-string"
  - type: partial
    value: "substring"
  - type: regex
    regex: "ORDER-\\d{4}"
```

### AVRO Support

**Reading AVRO messages**:
- Messages are automatically deserialized from binary
- Displayed as JSON objects in API responses
- Can be matched with JSONPath conditions

**Producing AVRO messages**:
- Specify `schema_id` in rule output to produce AVRO
- Message payload is rendered as JSON, then AVRO-encoded
- Requires Confluent Schema Registry configured

**Example AVRO output rule**:
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

### Custom Placeholders

Create custom placeholder functions in Python files in `/config/custom_placeholders/`. Placeholders execute in a **pipeline** - each stage sees results from all previous stages.

**Key Features**:
- ✅ Unordered placeholders execute **first**
- ✅ Ordered placeholders execute **second** (by order number)
- ✅ Each placeholder sees results from previous executions
- ✅ Hot-reload every 30 seconds
- ✅ Support both `PLACEHOLDERS` dict and `@placeholder` decorator

**Example: Business Logic**:

`/config/custom_placeholders/10-business_logic.py`:
```python
def calculate_discount(context):
    """Calculate discount based on amount"""
    amount = float(context.get('$.amount', 0))
    return amount * 0.1 if amount > 1000 else 0.0

PLACEHOLDERS = {
    'discount': calculate_discount,
}
```

**Example: Using Previous Results**:

`/config/custom_placeholders/20-calculations.py`:
```python
from custom_placeholders import order, placeholder

@order(10)
@placeholder
def final_price(context):
    """See discount from stage 1"""
    amount = float(context.get('$.amount', 0))
    discount = float(context.get('discount', 0))  # Result from stage 1
    return amount - discount

@order(20)
@placeholder
def total_with_tax(context):
    """See final_price from @order(10)"""
    final = float(context.get('final_price', 0))
    tax = final * 0.08
    return final + tax
```

**Usage in Rules**:

```yaml
payload: |
  {
    "orderId": "{{$.orderId}}",
    "discount": "{{discount}}",
    "finalPrice": "{{final_price}}",
    "totalWithTax": "{{total_with_tax}}"
  }
```

**Execution Order**:
1. All unordered placeholders (no @order decorator)
2. Ordered placeholders (by @order value: 10, 20, 30, ...)

**Available Context**:
- All JSON fields from message: `$.fieldName`
- Built-in placeholders: `uuid`, `now`, `randomInt()`
- Results from previous placeholders: `placeholder_name`

### Example Configurations

See `/config/examples/` for working examples:

1. `01-exact-match.yaml` - Simple exact match
2. `02-jsonpath-multi-output.yaml` - JSONPath with multiple outputs
3. `03-regex-extraction.yaml` - Regex with capture groups
4. `01-order-created.yaml` - Real-world order processing
5. `02-wildcard-catchall.yaml` - Catch-all pattern
6. `03-placeholders.yaml` - All placeholder types
7. `04-multiple-regex.yaml` - Multiple conditions
8. `05-avro-output.yaml` - AVRO message output (produce AVRO)
9. `06-avro-input.yaml` - AVRO message input (consume & match AVRO)

## Schema Validation

A JSON Schema for validating rule configuration YAML files is provided at **`rule-schema.json`** in the project root. Use it to catch configuration errors early in your editor or CI pipeline.

### Schema Location

```
rule-schema.json   ← JSON Schema Draft 7
```

### IDE Integration

#### VS Code

Install the [YAML extension by Red Hat](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml), then add the following to your `.vscode/settings.json`:

```json
{
  "yaml.schemas": {
    "./rule-schema.json": "config/**/*.yaml"
  }
}
```

This enables in-editor validation, auto-complete, and hover documentation for all rule files under `config/`.

#### IntelliJ IDEA / PyCharm

1. Open **Settings** → **Languages & Frameworks** → **Schemas and DTDs** → **JSON Schema Mappings**
2. Click **+** to add a new mapping
3. Set **Schema file**: path to `rule-schema.json` in the project root
4. Set **File path pattern**: `config/**/*.yaml`
5. Click **OK**

### Command-Line Validation

#### Using `check-jsonschema` (Python, recommended)

```bash
# Install
pip install check-jsonschema

# Validate a single rule file
check-jsonschema --schemafile rule-schema.json config/rules/my-rule.yaml

# Validate all rule files at once (bash with globstar enabled)
check-jsonschema --schemafile rule-schema.json config/**/*.yaml

# Alternative using find (works in all POSIX shells)
find config -name '*.yaml' -exec check-jsonschema --schemafile rule-schema.json {} +
```

#### Using `ajv-cli` (Node.js)

```bash
# Install
npm install -g ajv-cli ajv-formats

# Validate a rule file
ajv validate -s rule-schema.json -d config/rules/my-rule.yaml
```

### CI/CD Integration

Add a validation step to your pipeline to prevent invalid rules from being deployed:

```yaml
# GitHub Actions example
- name: Validate rule configuration
  run: |
    pip install check-jsonschema
    check-jsonschema --schemafile rule-schema.json config/**/*.yaml
```

## API Endpoints

### Health Check

```bash
GET /health
```

Response:
```json
{
  "status": "ok"
}
```

### Inject Message

```bash
POST /inject/<topic>
Content-Type: application/json
schema-id: 123  # Optional header for AVRO schema ID

{
  "message": { "key": "value" } | "string"
}
```

Response:
```json
{
  "message_id": "orders-0-42",
  "topic": "orders",
  "status": "success"
}
```

### Get Messages from Topic

```bash
GET /messages/<topic>?limit=10
```

Query Parameters:
- `limit`: Number of messages to retrieve (1-100, default: 10)

Response includes messages in JSON or AVRO (decoded to JSON):
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

### List All Rules

```bash
GET /rules
```

Response:
```json
[
  {
    "name": "order-to-shipment",
    "priority": 10,
    "match_strategy": "exact",
    "match_condition": "order-created",
    "input_topic": "orders",
    "outputs": [
      {
        "topic": "shipments",
        "message_template": "{ \"status\": \"ok\" }"
      }
    ]
  }
]
```

### List Rules for Specific Topic

```bash
GET /rules/<input_topic>
```

Response: Same as `/rules` but filtered for the topic.

## Environment Variables

- `KAFKA_BOOTSTRAP_SERVERS` (default: `localhost:9092`)
- `CONFIG_DIR` (default: `/config`)
- `HOST` (default: `0.0.0.0`)
- `PORT` (default: `8000`)
- `WORKERS` (default: `1`)

## Local Development

### Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Run Locally

```bash
# Start Kafka locally (e.g., Docker)
docker-compose up -d kafka zookeeper

# Run the app
python run.py
```

The app will be available at `http://localhost:8000`.

### Testing Configuration

Create a test config file in `/config`:

```yaml
rules:
  - name: "test-rule"
    priority: 1
    match_strategy: "partial"
    match_condition: "test"
    input_topic: "test-input"
    outputs:
      - topic: "test-output"
        message_template: "Response to: {{ full_message }}"
```

Then:

```bash
# Inject a test message
curl -X POST http://localhost:8000/inject/test-input \
  -H "Content-Type: application/json" \
  -d '{"message": "this is a test"}'

# Check the output
curl http://localhost:8000/messages/test-output
```

## Integration with Docker Compose

To add Kafka Wiremock to your existing docker-compose:

```yaml
services:
  kafka-wiremock:
    build:
      context: ./kafka-wiremock  # Path to this repo
      dockerfile: Dockerfile
    depends_on:
      kafka:
        condition: service_healthy
    ports:
      - "8000:8000"
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:29092  # Use internal broker address
      CONFIG_DIR: /config
    volumes:
      - ./kafka-wiremock/config:/config
    networks:
      - app-network
```

## Troubleshooting

### No config files loaded

- Check that YAML files are in the `/config` directory
- Ensure filenames end with `.yaml` or `.yml`
- Check logs: `docker-compose logs kafka-wiremock`

### Messages not being produced

- Verify Kafka is healthy: `docker-compose logs kafka` should show no errors
- Check that the input topic exists or auto-creation is enabled
- Review logs for matching errors

### Placeholder substitution not working

- Verify placeholder names match available context keys
- Use `GET /rules/<topic>` to check rule configuration
- Check logs for warnings about missing placeholders

### Hot-reload not working

- Config files are checked every 30 seconds
- Ensure files are saved (not just edited)
- Restart container if issues persist

## Limitations

- **No message persistence**: Messages are not stored; only current in-flight messages are processed
- **Single match per message**: First matching rule is executed; subsequent rules are skipped
- **No correlation tracking**: No built-in way to correlate input/output messages

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  External Systems / Tests                            │
│  (POST /inject/topic)                               │
└──────────────────┬──────────────────────────────────┘
                   │
         ┌─────────▼──────────┐
         │   FastAPI Server   │
         │   (port 8000)      │
         └─────────┬──────────┘
                   │
        ┌──────────┴────────┬──────────────┐
        │                   │              │
        │            ┌──────▼──────┐      │
        │            │ Kafka       │      │
        │            │ Producer    │      │
        │            └─────────────┘      │
        │                                  │
        │ /inject endpoint                 │
        │                                  │
        │            ┌──────────────────┐  │
        │            │ Config Loader    │  │
        │            │ (hot-reload 30s) │  │
        │            └──────────────────┘  │
        │                                  │
        │      ┌─────────────────────┐    │
        │      │ Kafka Listener      │    │
        │      │ Threads (per topic) │    │
        │      └────────┬────────────┘    │
        │               │                  │
        │      ┌────────▼────────┐        │
        │      │ Matcher Engine  │        │
        │      │ (4 strategies)  │        │
        │      └────────┬────────┘        │
        │               │                  │
        │      ┌────────▼──────────┐      │
        │      │ Template Renderer │      │
        │      └────────┬──────────┘      │
        │               │                  │
        │      ┌────────▼─────────┐       │
        └─────►│ Kafka Producer   │       │
               │ (to output       │       │
               │  topics)         │       │
               └──────────────────┘       │
                         │                │
         ┌───────────────▼────────────────┤
         │  Kafka Topics                  │
         │  (input & output)              │
         └────────────────────────────────┘
```

## Test Suite Feature

The Test Suite allows you to define integration tests that verify your Kafka event flows end-to-end. Tests can inject messages, wait for expected outputs, and validate using custom Python scripts.

### Quick Start: Running Tests

#### 1. List all available tests
```bash
curl http://localhost:8000/tests
```

#### 2. Run a single test
```bash
curl -X POST http://localhost:8000/tests/simple-injection-test
```

#### 3. Run all tests in parallel (10 iterations each)
```bash
curl -X POST "http://localhost:8000/tests:bulk?mode=parallel&threads=4&iterations=10"
```

#### 4. Run tests sequentially with tag filter
```bash
curl -X POST "http://localhost:8000/tests:bulk?mode=sequential&filter_tags=critical&filter_tags=e2e"
```

### Test Definition Format

Create test files in `/testSuite/` directory (any subdirectories) with `*.test.yaml` extension:

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

### Message Correlation

Use `source_id` and `target_id` to correlate injected messages with expected outputs:

```yaml
when:
  inject:
    - message_id: "order"       # Unique ID for this injection
      topic: "orders.input"
      payload: '{"orderId": "ORD-{{uuid}}", "amount": 50.0}'

then:
  expectations:
    - source_id: "order"        # Reference the injected message
      target_id: "$.orderId"    # Field in received message to match
      topic: "payments.input"
      # Wiremock will extract orderId from injected message
      # and match it against $.orderId in received messages
```

If `source_id`/`target_id` are not specified, **any message matching the conditions is accepted**.

### API Endpoints for Tests

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tests` | GET | List all discovered tests |
| `/tests/{test_id}` | GET | Get test definition |
| `/tests/{test_id}` | POST | Run single test |
| `/tests:bulk` | POST | Run all tests (sequential or parallel) |

**Query Parameters for `/tests:bulk`**:
- `mode`: `sequential` or `parallel` (default: `parallel`)
- `threads`: Number of concurrent threads (1-32, default: 4)
- `iterations`: Iterations per test (1-1000, default: 1)
- `filter_tags`: Tag names to filter (repeatable: `?filter_tags=tag1&filter_tags=tag2`)

### Test Result Format

```json
{
  "test_id": "order-flow-test",
  "status": "PASSED",           // PASSED, FAILED, SKIPPED, TIMEOUT
  "elapsed_ms": 1234,
  "when_result": {
    "injected": [
      {"message_id": "order1", "topic": "orders.input", "status": "ok"},
      {"message_id": "notif1", "topic": "notifications.input", "status": "ok"}
    ],
    "script_error": null
  },
  "then_result": {
    "expectations": [
      {
        "index": 0,
        "topic": "payments.input",
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

### Bulk Test Result Format

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
      "error": "Expectation failed for payments.input: timeout waiting for message",
      "elapsed_ms": 2001
    }
  ]
}
```

### Environment Variables

```bash
TEST_SUITE_DIR=/testSuite              # Directory for test files (default: /testSuite)
```

### Example Tests

See `/testSuite/examples/` for sample test files:
- `01-simple-injection.test.yaml` — Basic single injection + expectation
- `02-order-payment-flow.test.yaml` — Complex flow with multiple messages and correlation
- `03-multiple-conditions.test.yaml` — Tests with multiple validation conditions

## Docker Compose useful commands
```shell
docker-compose -f docker-compose.full.yml down  # Stop and remove all services
docker-compose -f docker-compose.full.yml build --no-cache  # Build all services without cache (useful after code changes)
docker-compose -f docker-compose.full.yml up -d  # Start all services
```

## Contributing

To add features or fix bugs:

1. Modify relevant files in `src/`
2. Test locally with docker-compose
3. Update documentation as needed

## License

MIT

