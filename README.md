# Kafka Wiremock

Event-driven Kafka and JMS mock container for testing, similar to Pact for APIs. Intercepts messages on Kafka topics and JMS queues, applies configurable matching rules, and produces replies with templated responses.

⚡ **Quick Start**: See **[QUICK_START_BUILD_FIX.md](QUICK_START_BUILD_FIX.md)** for latest build instructions and setup.

## Key Features

- ✅ **Kafka & JMS Support**: Use with Kafka topics and IBM MQ queues simultaneously
- ✅ **Mixed Message Flows**: Input from Kafka → Output to JMS (or vice versa)
- ✅ **Multiple Matching Strategies**: JSONPath, Regex, Exact, Partial matching
- ✅ **Rich Templating**: UUID, timestamps, random data, JSONPath extraction
- ✅ **Custom Placeholders**: User-defined functions with ordered pipeline execution
- ✅ **Multiple Outputs**: Single rule → multiple messages to different topics/queues
- ✅ **Message Headers**: Custom correlation IDs and headers
- ✅ **Execution Delays**: Simulate processing latency
- ✅ **Fault Injection**: Simulate failures (drop, duplicate, corruption, latency) in rules and tests
- ✅ **Skip Rules & Tests**: Disable rules/tests without removing them (set `skip: true`)
- ✅ **AVRO Support**: Read, match, and produce AVRO messages
- ✅ **Test Suite**: Integration tests with injection, correlation, and validation
- ✅ **Send Feature**: Simple message injection without test assertions (for quick testing)
- ✅ **Hot-Reload**: Configuration updates every 30 seconds (no restart needed)
- ✅ **Docker Ready**: Lightweight container with all dependencies included
- ✅ **Angular Web UI**: Modern dashboard for managing tests, sends, rules, and messages

## UI Features (Angular 19)

### Phase 1: Core Features (✅ Complete)

The Angular 19 web UI provides a modern dashboard for managing Kafka Wiremock:

#### 📊 Test Suite Manager
- **Multi-Select Tests**: Select multiple tests with checkboxes or "Select All"
- **Execution Modes**: Run tests sequentially or in parallel (1-16 workers)
- **Repeat Functionality**: Run each test N times (1-100)
- **Search & Filter**: Find tests by name or tags
- **Real-Time Results**: View pass/fail/skip status and execution time
- **Statistics**: Total, passed, failed, skipped counts with timing

#### 📮 Send Messages Manager
- **Multi-Select Sends**: Select multiple message definitions
- **Execution Modes**: Sequential or parallel execution
- **Repeat Functionality**: Repeat each send N times
- **Search & Filter**: Find sends by ID or tags
- **Execution Tracking**: Monitor send completion status

#### 📋 Rules Viewer & Tester
- **Rules Explorer**: Browse all configured rules with search
- **Detailed View**: See matching conditions and output topics
- **Test Rule Matching**: Test rules with sample payloads before deployment
- **Visual Condition Display**: Clear formatting of JSONPath, regex, and exact matches
- **Output Preview**: View all message outputs a rule will produce

#### 💌 Message Inspector & Injector
- **Inject Messages**: Send test messages to any topic
- **Consume Messages**: Read messages from topics with configurable limits
- **JSON Viewer**: Display message payloads with proper formatting
- **Copy to Clipboard**: Share or debug message content
- **Headers Display**: View message metadata and headers

#### 🔧 Advanced Debugging (Phase 2)

##### Rule Matching Debugger
- **Detailed Analysis**: See which conditions matched/failed for each rule
- **Three Views**:
  - First Match: Shows matching rule and outputs
  - All Rules: Compare analysis across all rules
  - Message Analysis: Inspect payload and topic
- **Visual Indicators**: Color-coded condition types and status badges
- **Context Extraction**: View variables available for template rendering
- **Optional Rule Filtering**: Test specific rules in isolation

##### Test Execution Logs
- **View All Logs**: Browse test execution history
- **Search & Filter**: Find logs by test ID
- **Lazy Loading**: Fast list loading, content loads on demand
- **Copy & Download**: Export logs for external analysis
- **Statistics**: Quick overview of test status distribution
- **Auto-Parse**: Automatically extracts JSON summaries from logs

##### Advanced Test Filtering
- **Tag Filtering**: Filter tests by tags with dropdown selector
- **Status Filtering**: Show active or skipped tests
- **Smart Search**: Combines text search with advanced filters (AND logic)
- **Dynamic Tags**: Auto-discovers available tags from tests
- **Reset Filters**: Quick clear of all filter selections

#### 🛠️ Advanced Tools (Phase 3)

##### Template Preview & Validation
- **Real-Time Rendering**: Test placeholder expressions with actual values
- **Comprehensive Reference**: Complete guide to all available placeholders
- **Built-in Functions**: UUID, timestamps, random data generation
- **Context Variables**: Extract values from message data
- **Custom Placeholders**: Auto-discover custom placeholder functions
- **Example Templates**: Pre-built patterns for quick testing
- **Export**: Copy rendered output to clipboard

##### Execution History & Analytics
- **Auto-Tracking**: Every test run automatically saved to local storage
- **Recent Executions**: View all test runs with statistics
- **Pass Rate Trend**: Visual comparison of execution quality over time

##### Configuration Management (Phase 4 - UI In Progress)
- **Topic Configurations**: View all Kafka/JMS topic message formats
- **Queue Manager Explorer**: Browse all JMS queue managers with connection status
- **Provider Discovery**: See available JMS providers and installation guidance
- **Pool Statistics**: Monitor connection pool utilization in real-time
- **Configuration Export**: Download entire configuration as JSON

## JMS Multi-Provider Support (Phase 3)

**Status**: ✅ Backend Complete | 🔄 UI In Progress

Kafka Wiremock now supports multiple JMS providers in parallel with automatic provider detection:

### Supported JMS Providers

| Provider | Status | Library | Pooling | Notes |
|----------|--------|---------|---------|-------|
| **IBM MQ** | ✅ Full | `pymqi@1.12.13` (Public PyPI) | ✅ | **Recommended for all use cases** - Docker-compose ready |
| **ActiveMQ** | ✅ Full | `stomp.py@8.1.0` | ✅ | STOMP over TCP |
| **RabbitMQ** | ✅ Full | `pika@1.3.0` | ✅ | AMQP with vhost support |

### Configuration Example

```yaml
queue_managers:
  qm_primary:
    provider: ibm_mq
    broker_url: ibmmq.example.com(1414)
    channel: PROD.SVRCONN
    queue_manager: QM_PROD
    username: app_user
  
  qm_backup_activemq:
    provider: activemq
    broker_url: activemq-backup:61613
    username: admin

  qm_rabbitmq:
    provider: rabbitmq
    broker_url: rabbitmq.example.com:5672
    username: guest
    virtual_host: /
```

### Mixed Message Flows

Rules can mix Kafka and JMS in the same flow:

```yaml
when:
  topic: ORDERS_INPUT
  msg_type: jms              # Input from JMS queue
  queue_manager_ref: qm_primary

then:
  - topic: orders.events
    msg_type: kafka          # Output to Kafka
    payload: '{"orderId": "{{$.orderId}}", "source": "jms"}'

  - topic: ORDERS_NOTIFY
    msg_type: jms            # Also notify via another JMS queue
    queue_manager_ref: qm_backup_activemq
    payload: '{"orderId": "{{$.orderId}}"}'
```

### Hybrid Provider Selection (Option C)

Kafka Wiremock uses automatic provider detection with manual override:

1. **Auto-Detection**: Checks installed libraries at startup
2. **Available Reporting**: API shows which providers are available
3. **Explicit Override**: Use `queue_manager_ref` to specify which provider to use
4. **Graceful Fallback**: Missing provider → Error with installation instructions

### Configuration Viewer API

**New REST endpoints** for viewing configurations:

```bash
# View all topics
GET /api/config/topics

# View specific topic with correlation rules
GET /api/config/topics/{topic}

# List all queue managers with status
GET /api/config/jms-queue-managers

# View queue manager with pool stats
GET /api/config/jms-queue-managers/{qm_name}

# Discover available JMS providers
GET /api/jms/providers
```

### Connection Pooling

All JMS providers support configurable connection pooling:

```yaml
queue_managers:
  qm_primary:
    provider: ibm_mq
    # ... connection details ...
    pool:
      min_idle: 2              # Min connections to keep alive
      max_size: 10             # Max connections in pool
      max_wait_ms: 5000        # Timeout waiting for connection
      auto_reconnect: true     # Reconnect on failure
      reconnect_attempts: 3    # Number of retries
```

### Environment Variables

Provider-specific configuration via environment:

```bash
# Queue manager passwords
export JMS_QM_PRIMARY_PASSWORD="secret123"
export JMS_QM_BACKUP_ACTIVEMQ_PASSWORD="secret456"

# Provider override (force specific provider)
export JMS_PROVIDER_OVERRIDE="rabbit mq"

# IBM MQ specifics
export IBM_MQ_BROKER_URL="ibmmq.example.com(1414)"
export IBM_MQ_CHANNEL="PROD.SVRCONN"
```

| - **Auto-Tracking**: Every test run automatically saved to local storage
| - **Recent Executions**: View all test runs with statistics
| - **Pass Rate Trend**: Visual comparison of execution quality over time

## JMS Support (May 2026)

Kafka Wiremock now supports IBM MQ for JMS messaging alongside Kafka, enabling:

### Features
- **IBM MQ Integration**: Connect to IBM Message Queue systems
- **Mixed Workloads**: Input from Kafka → Output to JMS (or vice versa)
- **JMS Configuration Files**: Similar to topic-config, store JMS-specific settings in `config/jms-config/`
- **Flexible Routing**: Rules can output to Kafka, JMS queues, or both
- **Message Type Detection**: Specify `msg_type` to route messages appropriately

### Quick Start: IBM MQ with Docker Compose

**✅ Recommended: Use Docker Compose with Official IBM MQ Container**

The easiest way to get started with IBM MQ is using the included `docker-compose.full.yml` which provides a complete development environment:

```bash
# Start everything (Kafka, Zookeeper, IBM MQ, and Kafka Wiremock)
docker-compose -f docker-compose.full.yml up -d

# Wait for services to be healthy
docker-compose -f docker-compose.full.yml ps

# Verify IBM MQ is ready
docker-compose -f docker-compose.full.yml logs ibm-mq | grep "QM1"
```

**What you get automatically:**
- ✅ Official IBM MQ 9.3 container (QM1 queue manager)
- ✅ Pre-created test queues (ORDERS_INPUT, ORDERS_OUTPUT, PAYMENTS_INPUT, etc.)
- ✅ Python app with JMS support (Kafka, ActiveMQ, RabbitMQ)
- ✅ All test/example queues initialized
- ✅ Health checks to verify everything is ready

**Note on IBM MQ Library Support:**
The Docker image attempts to install `pymqi` for IBM MQ support. If pymqi compilation fails due to missing IBM MQ C libraries, the build will complete anyway with other JMS providers (stomp.py, pika) still available. See [PYMQI_INSTALLATION_GUIDE.md](PYMQI_INSTALLATION_GUIDE.md) for details.

**Access IBM MQ Admin Console:**
```
URL: https://localhost:9443/ibmmq/console/
Username: admin
Password: passw0rd
```

**Verify IBM MQ Queue Configuration:**
```bash
# Check queue status
docker-compose -f docker-compose.full.yml exec ibm-mq dspmq -m QM1

# Verify pre-created queues
docker-compose -f docker-compose.full.yml exec ibm-mq runmqsc -m QM1 << EOF
DISPLAY QLOCAL(ORDERS_INPUT)
DISPLAY QLOCAL(ORDERS_OUTPUT)
EOF
```

For comprehensive setup guide, troubleshooting, and advanced configuration:

👉 **See: [IBM_MQ_DOCKER_SETUP.md](IBM_MQ_DOCKER_SETUP.md)**

**pymqi Compilation & Docker Build:**

The Docker build gracefully handles pymqi installation:
- Attempts to install `pymqi==1.12.13` from PyPI (may use pre-built wheels if available)
- If pymqi compilation fails, continues with other JMS providers (stomp.py, pika)
- FastAPI, Kafka client, and core functionality always installed
- Build completes successfully even if pymqi unavailable

For detailed troubleshooting, installation options, and how to enable IBM MQ support:

👉 **See: [PYMQI_INSTALLATION_GUIDE.md](PYMQI_INSTALLATION_GUIDE.md)**

---

### Alternative: Manual IBM MQ Setup (Advanced)

If you prefer to use an external IBM MQ server or need custom configuration:

**1. Install IBM MQ Client Library**
```bash
# Option A: Use pymqi (open-source, recommended for Docker and most use cases)
pip install pymqi==1.12.13

# Option B: Use official ibm-mq (requires IBM repository credentials, not recommended)
pip install ibm-mq --index-url https://public.dhe.ibm.com/ibmdl/export/pub/software/websphere/messaging/mqpython/
```

**2. Configure JMS Connection (Environment Variables)**
```bash
export IBM_MQ_BROKER_URL="your-mq-server(1414)"
export IBM_MQ_CHANNEL="YOUR.SVRCONN"
export IBM_MQ_QUEUE_MANAGER="YOUR_QM"
export IBM_MQ_USERNAME="your_user"
export IBM_MQ_PASSWORD="your_password"
```

**3. Create JMS Configuration** (`config/jms-config/orders.yaml`)
```yaml
destination: YOUR_QUEUE_NAME
destination_type: queue
message:
  format: json
correlation:
  extract:
    - from: header
      name: X-Correlation-Id
      priority: 1
```

**4. Create a Rule with Mixed Input/Output** (`config/rules/jms-example.yaml`)
```yaml
priority: 10
name: "jms-to-kafka-rule"
when:
  topic: YOUR_QUEUE_NAME
  msg_type: jms  # Input from JMS
  match:
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CREATED"
then:
  # Output to Kafka
  - topic: orders.processed
    msg_type: kafka
    payload: |
      {
        "orderId": "{{$.orderId}}",
        "event": "PROCESSED"
      }
  # Output to another JMS queue
  - topic: ORDERS_PROCESSED
    msg_type: jms
    payload: |
      {
        "orderId": "{{$.orderId}}",
        "status": "processed"
      }
```

**5. Inject/Consume via API**
```bash
# Inject to JMS queue
curl -X POST "http://localhost:8000/api/inject/ORDERS_INPUT?msg_type=jms" \
  -H "Content-Type: application/json" \
  -d '{"orderId": "ORD-123", "eventType": "ORDER_CREATED"}'

# Consume from JMS queue
curl "http://localhost:8000/api/messages/ORDERS_PROCESSED?msg_type=jms&limit=5"
```

### Configuration Files

| Type | Location | Purpose |
|------|----------|---------|
| **JMS Config** | `config/jms-config/*.yaml` | Queue/topic metadata, properties, correlation |
| **Rules** | `config/rules/*.yaml` | Message matching and routing (supports `msg_type` field) |
| **Topic Config** | `config/topic-config/*.yaml` | Kafka topic config (unchanged) |

### Rule Structure for Mixed Messages

```yaml
priority: 10
when:
  topic: INPUT_QUEUE_OR_TOPIC
  msg_type: kafka  # or 'jms' - defaults to 'kafka'
  match:
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CREATED"
then:
  - topic: output.queue.or.topic
    msg_type: jms  # or 'kafka' - defaults to 'kafka'
    payload: |
      {
        "status": "processed"
      }
```

### Supported Message Types
- `kafka` (default) - Send/receive from Kafka topics
- `jms` - Send/receive from JMS queues via IBM MQ

### Environment Variables for IBM MQ
| Variable | Default | Description |
|----------|---------|-------------|
| `IBM_MQ_BROKER_URL` | `localhost(1414)` | Broker connection string |
| `IBM_MQ_CHANNEL` | `DEV.APP.SVRCONN` | Channel name |
| `IBM_MQ_QUEUE_MANAGER` | `QM1` | Queue manager name |
| `IBM_MQ_USERNAME` | _(none)_ | Username for authentication |
| `IBM_MQ_PASSWORD` | _(none)_ | Password for authentication |
| `IBM_MQ_SSL_KEY_STORE` | _(none)_ | Path to SSL keystore (PEM) |
| `IBM_MQ_SSL_KEY_STORE_PASSWORD` | _(none)_ | SSL keystore password |

### JMS Connection Pooling (May 2026)
| Variable | Default | Description |
|----------|---------|-------------|
| `JMS_POOLING_ENABLED` | `true` | Enable connection pooling for all queue managers |
| `JMS_POOL_MIN_IDLE` | `1` | Minimum number of idle connections per queue manager |
| `JMS_POOL_MAX_SIZE` | `5` | Maximum connections per pool |
| `JMS_POOL_MAX_WAIT_MS` | `5000` | Maximum wait time for connection availability (milliseconds) |
| `JMS_POOL_AUTO_RECONNECT` | `true` | Enable automatic reconnection on connection failure |
| `JMS_POOL_RECONNECT_ATTEMPTS` | `3` | Number of reconnection retry attempts |
| `JMS_POOL_RECONNECT_DELAY_MS` | `1000` | Initial delay between reconnection attempts (milliseconds) |

## Recent Improvements (May 2026)

### Phase 2: Connection Pooling & Auto-Reconnect (May 9, 2026)

✅ **Connection Pooling**: Reuse JMS connections within registry for improved performance  
✅ **Auto-Reconnect**: Automatic failure detection and recovery with exponential backoff  
✅ **Connection Lifecycle**: Automatic cleanup of idle and expired connections  
✅ **Thread-Safe**: Concurrent access with proper synchronization  
✅ **Monitoring**: Real-time pool statistics via API endpoint  
✅ **Configuration**: Environment-based tuning for pool size, timeouts, and retry behavior  

See `PHASE2_IMPLEMENTATION_COMPLETE.md` for detailed implementation information.

#### Features
- **Min/Max Pool Size**: Control connection bounds (default: min=1, max=5)
- **Idle Cleanup**: Automatic removal of unused connections (default: 15 minutes)
- **Auto-Reconnect**: Exponential backoff retry on connection failure
- **Test-on-Borrow**: Optional connection validation before use
- **Statistics API**: Real-time metrics for pool health

#### Environment Variables for JMS Connection Pooling
```bash
JMS_POOLING_ENABLED=true                    # Enable pooling (default: true)
JMS_POOL_MIN_IDLE=1                         # Minimum idle connections
JMS_POOL_MAX_SIZE=5                         # Maximum pool size
JMS_POOL_MAX_WAIT_MS=5000                   # Max wait for connection
JMS_POOL_AUTO_RECONNECT=true                # Enable auto-reconnect
JMS_POOL_RECONNECT_ATTEMPTS=3               # Reconnect retry count
JMS_POOL_RECONNECT_DELAY_MS=1000            # Delay between retries
```

#### Check Pool Statistics
```bash
curl http://localhost:8000/api/jms/pool-stats
```

Response:
```json
{
  "status": "ok",
  "pooling_enabled": true,
  "pools": {
    "qm1": {
      "queue_manager": "qm1",
      "available": 2,
      "in_use": 1,
      "total": 3,
      "max_size": 5
    }
  }
}
```

### Phase 4: Bulk Execution & UI Fixes (Previous - May 7, 2026)

#### Bug Fixes
✅ **Logs Display Issue**: Fixed frontend logs component to properly parse API response structure (logs array in response object)  
✅ **Rule Matching Test - Key & Headers Support**: UI now allows users to test rules with optional message key and headers in addition to payload  
✅ **Rule Matching Debugger**: Added clear explanation of tool purpose - tests message against ALL rules, showing which matches first (in priority order)  

#### Enhancements
✅ **Test Logs API Response**: Updated logs endpoint to return structured response with log file metadata (path, size, modified time)  
✅ **Backend Rule Matching**: `/rules:match` endpoint now supports optional key and headers parameters for comprehensive rule testing  
✅ **UI Clarity**: Rule Matching Debugger now displays information panel explaining:
   - Which rule matches first (in priority order)
   - Why rules matched or failed (per condition analysis)
   - What output messages would be produced
   - Context variables extracted for template rendering
   - Rule name filtering is optional (tests all rules if not specified)

#### How to Use the Fixes

**Testing Logs:**
- Logs endpoint `/tests/logs` now properly displays test execution history in the frontend
- Each log shows relative path, size, modification time, and content preview
- Click to expand and view full log content

**Testing Rules with Key & Headers:**
In Rules > Test Rule Matching section:
 - **Message Key** (optional): Set a key for key-based condition matching
 - **Message Headers** (JSON, optional): Set headers for header-based condition matching
 - **Message Payload**: Set the JSON payload
 - Results show if rule matches and which output messages would be produced

**Rule Matching Debugger Purpose:**
- Located in Debugging > Rule Matcher
- **Different from Rules testing**: This tests a message against ALL rules (not just one)
- Shows first matching rule with details:
  - Which conditions matched/failed
  - Extracted context variables
  - Generated output messages
- Optional filtering to specific rule by name
- Takes optional key and headers for complete message metadata testing

### Phase 4: Core Improvements (Previous)

✅ **Phase 4 Complete**: Bulk execution enhancement with summary prompts  
✅ **SQLite Persistence**: Results saved to database with cleanup API  
✅ **Configurable Repeat Semantics**: Choose execution order (interleaved/sequential)  
✅ **Feature Parity**: Tests and Sends components fully aligned  
✅ **Type Safety**: TypeScript models fixed for full type checking  
✅ **Execution History**: Both components save to localStorage  
✅ **Stop Button**: Cancel running executions  

See `IMPLEMENTATION_SUMMARY.md` for detailed changes and `TESTING_GUIDE.md` for testing procedures.


### 1. Using Docker Compose

```bash
# Start all services (Kafka + Zookeeper + Kafka Wiremock)
docker-compose up -d

# Check if Kafka Wiremock is healthy
curl http://localhost:8000/health
```

### 2. Starting the UI (Development)

```bash
# Terminal 1: Start backend
python3 run.py

# Terminal 2: Start Angular UI
cd ui
npm install
npm start

# Open browser to http://localhost:4200
```

### 3. Inject a Test Message

```bash
curl -X POST http://localhost:8000/inject/orders \
  -H "Content-Type: application/json" \
  -d '{"message": "order-created"}'
```

### 4. Check Produced Messages

```bash
curl http://localhost:8000/messages/shipments?limit=10
```

### 5. View Configured Rules

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

### Send Feature (May 2026)

Simple message injection without test assertions. Perfect for quick manual testing without the overhead of full test suites.

**Use Cases**:
- Quick ad-hoc message generation
- Manual system testing
- Load generation
- Demo and debugging

**Comparison with Test Suite**:

| Feature | Send | Test Suite |
|---------|------|-----------|
| **Inject messages** | ✅ | ✅ |
| **Check results** | ❌ | ✅ |
| **Scripts** | ✅ | ✅ |
| **Complexity** | Minimal | Full |
| **Typical use** | Quick send | Automated validation |

**Example Send Definition**:
```yaml
priority: 10
name: "send-orders"
tags: ["example", "order"]

inject:
  - message_id: "order1"
    topic: "orders.input"
    payload: |
      {
        "orderId": "{{uuid}}",
        "customerId": "CUST-123",
        "amount": 99.99,
        "status": "NEW"
      }
    delay_ms: 100
  
  - message_id: "order2"
    topic: "orders.input"
    payload: |
      {
        "orderId": "{{uuid}}",
        "customerId": "CUST-456",
        "amount": 199.99,
        "status": "NEW"
      }
```

**API Usage**:
```bash
# List all sends
curl http://localhost:8000/send

# Get send definition
curl http://localhost:8000/send/send-orders

# Run a send
curl -X POST http://localhost:8000/send/send-orders
```

**JMS Support in Sends (May 2026)**:

You can inject messages into IBM MQ queues directly from sends, just like from rules:

```yaml
priority: 20
name: "send-jms-orders"
tags: ["example", "jms"]

inject:
  - message_id: "order1"
    topic: "ORDERS_INPUT"         # IBM MQ queue name
    msg_type: jms                 # Specify JMS as destination type
    queue_manager_ref: qm_dev_local  # Optional: specify queue manager (uses default if omitted)
    payload: |
      {
        "orderId": "ORD-001",
        "customerId": "CUST-123",
        "amount": 99.99,
        "eventType": "ORDER_CREATED"
      }
    delay_ms: 100
```

See [send/examples/04-send-jms-orders.send.yaml](send/examples/04-send-jms-orders.send.yaml) for a complete example.

## Documentation

For detailed configuration and usage, see:

| Topic | Documentation |
|-------|---|
| **JMS Support** | [📘 JMS.md](docs/JMS.md) - IBM MQ integration, mixed Kafka/JMS workflows, configuration |
| **Topic Configuration** | [📘 TOPIC_CONFIG.md](docs/TOPIC_CONFIG.md) - Message format, schema registry, correlation rules |
| **Rules Configuration** | [📘 RULES.md](docs/RULES.md) - Matching strategies, outputs, templates, AVRO support, msg_type |
| **Custom Placeholders** | [📘 CUSTOM_PLACEHOLDERS.md](docs/CUSTOM_PLACEHOLDERS.md) - Creating custom functions, pipeline execution, examples |
| **Test Suite** | [📘 TEST_SUITE.md](docs/TEST_SUITE.md) - Integration tests, message correlation, validation |
| **API Reference** | [📘 API.md](docs/API.md) - Complete HTTP API endpoints and examples |

### Directory Structure

```
config/
├── topic-config/                   # Kafka topic configuration (message format, correlation)
│   ├── orders/
│   │   └── 01-orders.yaml
│   └── ...
├── jms-config/                     # JMS queue configuration (IBM MQ)
│   ├── orders/
│   │   └── 01-orders.yaml
│   └── ...
├── rules/                          # Rule matching and output generation (Kafka + JMS)
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

send/                               # Simple message sends (injection without assertions)
├── examples/
│   └── *.send.yaml
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
| `GET /app-settings` | Get application settings |
| `POST /app-settings` | Update application settings |
| `POST /inject/<topic>` | Inject a message into a Kafka topic |
| `GET /messages/<topic>` | Consume messages from a Kafka topic |
| `GET /rules` | List all configured rules |
| `GET /rules/<topic>` | List rules for a specific topic |
| `POST /rules:match` | Dry-run: show which rule would match a message |
| `GET /custom-placeholders` | List custom placeholder functions |
| `GET /dependencies` | Python dependency manager status |
| `GET /send` | List all send definitions |
| `GET /send/{send_id}` | Get a specific send definition |
| `POST /send/{send_id}` | Run a single send (inject messages) |
| `GET /tests` | List all test definitions |
| `GET /tests/{test_id}` | Get a specific test definition |
| `POST /tests/{test_id}` | Run a single test |
| `POST /tests:bulk` | Run all tests (bulk, parallel or sequential) |
| `GET /tests/jobs` | List async test jobs |
| `GET /tests/jobs/{job_id}` | Get async test job status |
| `GET /tests/logs` | List test log files |
| `GET /tests/logs/{test_id}` | Get log for a specific test |
| `GET /jms/pool-stats` | Get JMS connection pooling statistics (May 2026) |
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
| Variable | Default | Description |
| `HOST` | `0.0.0.0` | Bind address for the HTTP server |
| `PORT` | `8000` | HTTP API port |
| `WORKERS` | `1` | Number of Uvicorn worker processes |
| `CONFIG_DIR` | `/config` | Root directory for rules and topic-config files |
| `CUSTOM_PLACEHOLDERS_DIR` | `/config/custom_placeholders` | Directory for custom Python placeholder functions |
| `PYTHON_REQUIREMENTS_DIR` | `/config/python-requirements` | Directory scanned for `requirements.txt` to auto-install |
| `PYTHON_REQUIREMENTS_SCAN_INTERVAL` | `30` | Seconds between `requirements.txt` change checks |
| `TEST_SUITE_DIR` | `/testSuite` | Directory for `*.test.yaml` integration test files |
| `SEND_DIR` | `/send` | Directory for `*.send.yaml` simple message sends (no assertions) |
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

## Application Settings

Global UI and behavior settings are stored in `config/app-settings.json`. This file persists across container recreation (if `/config` is mounted as a volume).

### App Settings File

**Location**: `/config/app-settings.json`

**Default Content**:
```json
{
  "ui": {
    "test_recap_threshold": 100
  }
}
```

### Configuration Options

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `ui.test_recap_threshold` | integer | `100` | **Test Recap Popup Threshold**: Show the confirmation popup when test executions exceed this value. Set to `0` to always show, or higher values to show less frequently. This helps prevent confirmation fatigue on large test runs. |

### Managing Settings

#### Via Web UI

1. Click the **Settings** button (⚙️) in the top-right corner of the toolbar
2. Adjust the "Test Recap Threshold" value
3. Click "Save Settings"
4. Settings are instantly saved to `config/app-settings.json`

#### Via Configuration File

Edit `/config/app-settings.json` directly:

```json
{
  "ui": {
    "test_recap_threshold": 50
  }
}
```

Changes are automatically detected and reloaded every 30 seconds (no restart needed).

#### Via API

**Get current settings**:
```bash
curl http://localhost:8000/api/app-settings | jq
```

**Update settings**:
```bash
curl -X POST http://localhost:8000/api/app-settings \
  -H "Content-Type: application/json" \
  -d '{
    "ui": {
      "test_recap_threshold": 200
    }
  }' | jq
```



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

**Web UI**: The Angular frontend is automatically integrated and served at the root path. Visit `http://localhost:8000` to access the dashboard.

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
curl http://localhost:8000/api/tests

# Run a single test
curl -X POST http://localhost:8000/api/tests/order-flow-test

# Run all tests in parallel
curl -X POST "http://localhost:8000/api/tests:bulk?mode=parallel&iterations=10"

# Run tests with tag filtering
curl -X POST "http://localhost:8000/api/tests:bulk?filter_tags=critical&filter_tags=e2e"
```

Test files go in `/testSuite/` directory with `*.test.yaml` extension. See `/testSuite/examples/` for working examples.

## API Endpoints

All REST API endpoints are served under the `/api` prefix for a unified namespace:

```
GET    /api/health                  # Health check
GET    /api/tests                   # List all tests
POST   /api/tests:bulk              # Run tests in bulk
GET    /api/send                    # List all sends
POST   /api/send:bulk               # Execute sends in bulk
GET    /api/rules                   # Get all rules
GET    /api/rules/{topic}           # Get rules for a topic
POST   /api/rules:match             # Test rule matching with message
POST   /api/inject/{topic}          # Inject message to topic
GET    /api/messages/{topic}        # Get messages from topic
GET    /api/jms/pool-stats          # Get JMS connection pooling statistics
GET    /api/debug/topics            # List discovered topics
GET    /api/debug/cache             # View message cache stats
POST   /api/debug/decode            # Decode message payload
POST   /api/debug/match             # Debug rule matching
POST   /api/debug/template/render   # Render template with context
GET    /api/custom-placeholders     # List custom placeholder functions
GET    /api/dependencies            # List dependencies
```

The frontend served by the container automatically connects to these `/api/*` endpoints. When running the Angular dev server locally, the proxy configuration in `ui/proxy.conf.json` routes `/api` requests to the backend.

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

