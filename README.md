# Kafka Wiremock

Event-driven Kafka mock container for testing, similar to Pact for APIs. Intercepts messages on Kafka topics, applies configurable matching rules, and produces replies with templated responses.

## Key Features

- ✅ **Multiple Matching Strategies**: JSONPath, Regex, Exact, Partial matching
- ✅ **Rich Templating**: UUID, timestamps, random data, JSONPath extraction
- ✅ **Custom Placeholders**: User-defined functions with ordered pipeline execution
- ✅ **Multiple Outputs**: Single rule → multiple messages to different topics
- ✅ **Message Headers**: Custom correlation IDs and headers
- ✅ **Execution Delays**: Simulate processing latency
- ✅ **Fault Injection**: Simulate failures (drop, duplicate, corruption, latency) in rules and tests
- ✅ **Skip Rules & Tests**: Disable rules/tests without removing them (set `skip: true`)
- ✅ **AVRO Support**: Read, match, and produce AVRO messages
- ✅ **Test Suite**: Integration tests with injection, correlation, and validation
- ✅ **Hot-Reload**: Configuration updates every 30 seconds (no restart needed)
- ✅ **Docker Ready**: Lightweight container with all dependencies included

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

## What's New (April 2026)

### Fault Injection Engine

Simulate realistic failure scenarios in both rules and test injections:

```yaml
# In rules
fault:
  drop: 0.1              # 10% drop rate
  duplicate: 0.05        # 5% duplication
  poison_pill: 0.1       # 10% corruption
  random_latency: 0-500  # 0-500ms random delay
  poison_pill_type: ["truncate", "invalid-json", "corrupt-headers"]
  check_result: false    # For tests: skip expectations when fault applied

# In test injections
# Same structure - failures automatically tracked and expectations skipped
```

**Use Cases**:
- Test resilience handling of dropped messages
- Verify duplicate handling logic
- Validate corruption recovery
- Test response timing requirements

### Rule & Test Skip Feature

Disable rules and tests without removing them:

```yaml
# Temporarily disable this rule
skip: true

# Or in tests
skip: true
```

Useful for maintenance, A/B testing, and gradual rollouts.

## Documentation

For detailed configuration and usage, see:

| Topic | Documentation |
|-------|---|
| **Topic Configuration** | [📘 TOPIC_CONFIG.md](docs/TOPIC_CONFIG.md) - Message format, schema registry, correlation rules |
| **Rules Configuration** | [📘 RULES.md](docs/RULES.md) - Matching strategies, outputs, templates, AVRO support |
| **Custom Placeholders** | [📘 CUSTOM_PLACEHOLDERS.md](docs/CUSTOM_PLACEHOLDERS.md) - Creating custom functions, pipeline execution, examples |
| **Test Suite** | [📘 TEST_SUITE.md](docs/TEST_SUITE.md) - Integration tests, message correlation, validation |
| **API Reference** | [📘 API.md](docs/API.md) - Complete HTTP API endpoints and examples |

### Directory Structure

```
config/
├── topic-config/                   # Topic configuration (message format, correlation)
│   ├── orders/
│   │   └── 01-orders.yaml
│   └── ...
├── rules/                          # Rule matching and output generation
│   ├── order-processing/
│   │   ├── 01-order-created.yaml
│   │   └── 02-order-shipped.yaml
│   └── ...
└── custom_placeholders/            # Python placeholder functions
    ├── business/
    │   └── 10-discounts.py
    └── ...

testSuite/                          # Integration tests (message injection and validation)
├── examples/
│   └── *.test.yaml
└── ...
```

**Files are scanned recursively** - organize by subdirectories as your project grows!

## Schema Validation

JSON Schema validators are provided for topic config, rules, and tests:

| Schema | File | Description |
|--------|------|-------------|
| **Topic Config** | `topic-config-schema.json` | Validates topic configuration (format, correlation) | 
| **Rules** | `rule-schema.json` | Validates rule YAML configuration (matching, outputs, correlation) |
| **Tests** | `test-suite-schema.json` | Validates test suite YAML (injection, expectations, correlation) |

Use these for IDE integration, command-line validation, and CI/CD validation to catch configuration errors early.

## API Reference

See [API.md](docs/API.md) for complete documentation of all HTTP endpoints:

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Health check |
| `POST /inject/<topic>` | Inject a message into a Kafka topic |
| `GET /messages/<topic>` | Consume messages from a Kafka topic |
| `GET /rules` | List all configured rules |
| `GET /rules/<topic>` | List rules for a specific topic |
| `POST /rules:match` | Dry-run: show which rule would match a message |
| `GET /custom-placeholders` | List custom placeholder functions |
| `GET /dependencies` | Python dependency manager status |
| `GET /tests` | List all test definitions |
| `GET /tests/{test_id}` | Get a specific test definition |
| `POST /tests/{test_id}` | Run a single test |
| `POST /tests:bulk` | Run all tests (bulk, parallel or sequential) |
| `GET /tests/jobs` | List async test jobs |
| `GET /tests/jobs/{job_id}` | Get async test job status |
| `GET /tests/logs` | List test log files |
| `GET /tests/logs/{test_id}` | Get log for a specific test |
| `POST /debug/decode` | Decode a raw message and detect its format |
| `POST /debug/match` | Detailed rule-matching analysis for a message |
| `GET /debug/topics` | Show discovered topics and metadata |
| `GET /debug/cache` | Show message cache statistics |
| `POST /debug/template/render` | Render a template with a given context |

Quick example:
```bash
# Inject a message
curl -X POST http://localhost:8000/inject/orders \
  -H "Content-Type: application/json" \
  -d '{"orderId": "ORD-123", "amount": 99.99}'

# Get produced messages
curl http://localhost:8000/messages/payments?limit=10 | jq

# List rules
curl http://localhost:8000/rules | jq

# Dry-run: check which rule would match
curl -X POST "http://localhost:8000/rules:match?topic=orders" \
  -H "Content-Type: application/json" \
  -d '{"eventType": "ORDER_CREATED", "orderId": "ORD-1"}'
```

## Environment Variables

### General

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Bind address for the HTTP server |
| `PORT` | `8000` | HTTP API port |
| `WORKERS` | `1` | Number of Uvicorn worker processes |
| `CONFIG_DIR` | `/config` | Root directory for rules and topic-config files |
| `CUSTOM_PLACEHOLDERS_DIR` | `/config/custom_placeholders` | Directory for custom Python placeholder functions |
| `PYTHON_REQUIREMENTS_DIR` | `/config/python-requirements` | Directory scanned for `requirements.txt` to auto-install |
| `PYTHON_REQUIREMENTS_SCAN_INTERVAL` | `30` | Seconds between `requirements.txt` change checks |
| `TEST_SUITE_DIR` | `/testSuite` | Directory for `*.test.yaml` integration test files |
| `SCHEMA_REGISTRY_URL` | _(none)_ | Confluent Schema Registry URL for AVRO (e.g. `http://localhost:8081`) |

### Kafka Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker address(es) |
| `KAFKA_CONSUMER_GROUP_PREFIX` | `wiremock-consumer-` | Prefix for consumer group IDs |
| `KAFKA_CONSUME_FROM_LATEST` | `false` | When `true`, new consumers start from the latest offset instead of earliest |

### Kafka Security (SASL / SSL)

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_SECURITY_PROTOCOL` | `plaintext` | One of `plaintext`, `ssl`, `sasl_plaintext`, `sasl_ssl` |
| `KAFKA_SASL_MECHANISM` | `PLAIN` | SASL mechanism: `PLAIN`, `SCRAM-SHA-256`, or `SCRAM-SHA-512` (only when protocol includes SASL) |
| `KAFKA_SASL_USERNAME` | _(none)_ | SASL username |
| `KAFKA_SASL_PASSWORD` | _(none)_ | SASL password |
| `KAFKA_SSL_CA_LOCATION` | _(none)_ | Path to CA certificate file (PEM) |
| `KAFKA_SSL_CERTIFICATE_LOCATION` | _(none)_ | Path to client certificate file (PEM) |
| `KAFKA_SSL_KEY_LOCATION` | _(none)_ | Path to client private key file (PEM) |
| `KAFKA_SSL_KEY_PASSWORD` | _(none)_ | Password for the client private key |

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

## Test Suite

The Test Suite allows you to define integration tests that verify your Kafka event flows end-to-end. See [TEST_SUITE.md](docs/TEST_SUITE.md) for complete documentation.

Quick start:

```bash
# List tests
curl http://localhost:8000/tests

# Run a single test
curl -X POST http://localhost:8000/tests/order-flow-test

# Run all tests in parallel
curl -X POST "http://localhost:8000/tests:bulk?mode=parallel&iterations=10"

# Run tests with tag filtering
curl -X POST "http://localhost:8000/tests:bulk?filter_tags=critical&filter_tags=e2e"
```

Test files go in `/testSuite/` directory with `*.test.yaml` extension. See `/testSuite/examples/` for working examples.

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

