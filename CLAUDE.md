# Kafka Wiremock Project Context

## Project Overview
**kafka-wiremock** is a lightweight Kafka event mocking container for testing event-driven applications. It allows developers to inject messages into Kafka topics based on configurable rules and generate realistic event flows.

**Use Case**: Testing microservices that consume Kafka events without running the full event pipeline.

## Environment
- **Location**: WSL Ubuntu (Windows Subsystem for Linux)
- **Path**: `/home/nico/work/tools/kafka-wiremock`
- **Language**: Python 3
- **Framework**: FastAPI
- **Containerization**: Docker + Docker Compose

## Tech Stack
- **FastAPI**: REST API endpoints
- **Kafka**: Producer/Consumer using kafka-python
- **YAML**: Configuration format
- **JSONPath**: Message matching and extraction (jsonpath-ng)
- **Threading**: Background listener engine

## Architecture

### Core Components

| File | Purpose |
|------|---------|
| `src/main.py` | FastAPI endpoints (inject, consume, health, rules) |
| `src/kafka_listener.py` | Background engine processing Kafka messages against rules |
| `src/matcher.py` | Matching strategies (jsonpath, exact, partial, regex) |
| `src/templater.py` | Template rendering with placeholders (UUID, timestamps, etc) |
| `src/config_loader.py` | Hot-reload YAML config (30s interval) |
| `src/kafka_client.py` | Kafka producer/consumer wrapper with AVRO support |

### Configuration System (New)
- **Format**: One rule per YAML file in `/config/`
- **Structure**: `when` (matching) → `then` (output messages)
- **Features**: 
  - Multiple AND conditions
  - Wildcard matching (no conditions = catch all)
  - Headers support
  - Execution delays
  - Rich placeholders: `{{uuid}}`, `{{now}}`, `{{now+5m}}`, `{{randomInt()}}`, `{{$.field}}`

### Rule Matching
```yaml
when:
  topic: input-topic
  match:
    - type: jsonpath           # Extract & match JSON fields
      expression: "$.status"
      value: "CONFIRMED"       # Exact or...
      regex: "[0-9]+"          # Regex validation
    - type: exact              # Full message match
      value: "exact-string"
    - type: regex              # Regex on full message
      regex: "ORDER-\\d{4}"
```

**Important**: All conditions are ANDed (all must match)

### Template Placeholders
```
{{uuid}}                    # UUID v4
{{now}}                     # UTC ISO-8601 timestamp
{{now+5m}}                  # Timestamp + 5 minutes (m/h/d units)
{{randomInt(1,100)}}        # Random integer
{{$.fieldName}}             # JSONPath extraction
{{message}}                 # Full message object
```

## Key Features (Latest Implementation)

✅ **Flexible Matching**
- JSONPath with regex validation
- Multiple AND conditions
- Wildcard rules (catch-all)

✅ **Dynamic Templating**
- UUID generation
- Timestamp manipulation (now, offsets)
- Random data generation
- JSONPath extraction from input

✅ **Custom Placeholders** (NEW - April 2026)
- User-defined placeholder functions in Python
- Pipeline execution: unordered first, then by @order priority
- Each placeholder sees results from previous executions
- Hot-reload every 30 seconds
- Support both PLACEHOLDERS dict and @placeholder decorator

✅ **Production Features**
- Message headers with templating
- Execution delays (delay_ms)
- Multiple outputs per rule
- Rule priority sorting (lower = first)
- First-match-wins semantics

✅ **AVRO Support** (April 2026)
- **Read**: Automatically deserialize AVRO messages from topics
- **Match**: JSONPath conditions work on AVRO messages (decoded to JSON internally)
- **Produce**: Output AVRO messages with schema registry IDs (`schema_id` in rule)
- **Display**: AVRO messages shown as JSON in API responses

✅ **Developer Friendly**
- Hot reload (30s interval)
- Comprehensive logging
- API inspection endpoints
- Example configurations

## Running the Project

### Local Setup
```bash
cd kafka-wiremock
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Docker Compose
```bash
# Full stack (Kafka + Zookeeper + Wiremock)
docker-compose -f docker-compose.full.yml up -d

# Wiremock only
docker-compose up -d
```

### API Endpoints
```
POST   /inject/{topic}              # Inject message
GET    /messages/{topic}            # Get messages (limit param)
GET    /rules                       # View all rules
GET    /rules/{topic}               # View rules for topic
GET    /health                      # Health check
GET    /docs                        # Swagger UI
GET    /redoc                       # ReDoc
```

### Tests
```bash
# Run comprehensive tests
python3 test_new_format.py

# Specific test class
python3 test_new_format.py TestPlaceholders -v
```

## Configuration Examples

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
when:
  topic: transfers
  match:
    - type: jsonpath
      expression: "$.type"
      value: "TRANSFER"
    - type: jsonpath
      expression: "$.amount"
      regex: "^[0-9]{1,10}\\.[0-9]{2}$"  # Decimal format
    - type: jsonpath
      expression: "$.status"
      value: "PENDING"                    # All must match (AND)
```

### Example 3: Wildcard (Catch-all)
```yaml
priority: 999
when:
  topic: dlq
  # No match block = matches any message

then:
  - topic: dlq.archive
    payload: '{"archived": true, "archivedAt": "{{now}}"}'
```

## Important Patterns

### Context Building in kafka_listener.py
When a rule matches, context is built from matched fields:
- For JSONPath matches: Extracts all fields with `$.` prefix
- For regex matches: Capture groups available as-is (named or group_1, group_2, etc)
- Full message available as `message` key

### Template Rendering
- Placeholders are case-sensitive
- Missing placeholders return original placeholder text (logged as warning)
- Built-in functions work without context: `{{uuid}}`, `{{now}}`
- Context variables use: `{{$.field}}` (JSONPath style)

### Priority System
- Lower priority number = checked first
- Typical range: 10 (critical), 50 (normal), 100 (low), 999 (catch-all)
- First matching rule wins (no fall-through)

## File Structure
```
kafka-wiremock/
├── src/
│   ├── main.py              # FastAPI app
│   ├── kafka_listener.py    # Message processor
│   ├── matcher.py           # Matching logic
│   ├── templater.py         # Template engine
│   ├── config_loader.py     # Config management (recursive)
│   ├── kafka_client.py      # Kafka wrapper
│   └── custom_placeholders.py  # Custom placeholder registry
├── config/
│   ├── rules/               # Optional: organize rules by subdirectory
│   │   ├── order-processing/
│   │   │   ├── 01-order-created.yaml
│   │   │   └── 02-order-shipped.yaml
│   │   └── ...
│   ├── custom_placeholders/ # Optional: organize placeholders by subdirectory
│   │   ├── business/
│   │   │   └── 10-discounts.py
│   │   └── ...
│   └── examples/
│       └── (legacy examples)
├── test_new_format.py       # Comprehensive tests
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Compose (wiremock only)
├── docker-compose.full.yml  # Compose (with Kafka)
└── Dockerfile
```

**Key**: Both `/config/` and `/config/custom_placeholders/` scan **recursively** - users can organize files into subdirectories as needed!

## Code Patterns

### Adding a New Match Type
In `matcher.py`:
```python
class MyMatcher(Matcher):
    def match(self, message: Any, condition: Any) -> MatchResult:
        # Logic here
        return MatchResult(matched=bool, context={})
```

Then add to `MatcherFactory.STRATEGIES` dict.

### Adding a New Placeholder
In `templater.py`, update `_resolve_placeholder()`:
```python
if key == 'myplaceholder':
    return "computed value"
```

### Testing New Features
Use `test_new_format.py` as template:
```python
class TestMyFeature(unittest.TestCase):
    def test_something(self):
        # Arrange
        # Act
        # Assert
```

## Debugging Tips

### View Rules
```bash
curl http://localhost:8000/rules | jq
```

### Check Logs
```bash
docker-compose -f docker-compose.full.yml logs kafka-wiremock -f
docker-compose -f docker-compose.full.yml logs kafka-wiremock | grep -i error
```

### Test Message Flow
```bash
# Inject
curl -X POST http://localhost:8000/inject/test-topic \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'

# Consume
curl "http://localhost:8000/messages/output-topic?limit=5" | jq
```

### Syntax Check
```bash
python3 -m py_compile src/*.py
```

## Recent Work (April 2026)

Implemented new YAML configuration format with:
- Enhanced template engine (UUID, timestamps, random data)
- JSONPath + regex matching
- Message headers support
- Execution delays
- Multiple output messages per rule
- Wildcard rule matching
- Comprehensive test suite (400+ lines)

All changes maintain backward compatibility with old format.

## Performance Notes
- **Exact matching**: O(1) - Fastest
- **Partial matching**: O(n) - Fast string search
- **Regex matching**: O(n) - Compiled patterns cached
- **JSONPath**: O(1) + O(n) - Extraction then match
- **Config reload**: Background, every 30 seconds
- **Rule evaluation**: O(rules) where first match wins

## Common Issues

| Issue | Solution |
|-------|----------|
| Rule not matching | Check priority (higher priority rules checked first), verify JSONPath syntax |
| Placeholder not substituting | Use `{{$.field}}` for JSON, check spelling |
| Kafka won't connect | Set `KAFKA_BOOTSTRAP_SERVERS` env var, verify container health |
| Config not loading | Check YAML syntax, ensure `.yaml`/`.yml` extension, wait 30s for reload |
| Messages not produced | Check Kafka health, verify output topic exists |

## Environment Variables
- `KAFKA_BOOTSTRAP_SERVERS` - Kafka address (default: localhost:9092)
- `CONFIG_DIR` - Config directory (default: /config)
- `PORT` - API port (default: 8000)

## Dependencies
See `requirements.txt` for pinned versions. Key packages:
- fastapi
- kafka-python
- pyyaml
- jsonpath-ng
- uvicorn

---

**Quick Start**: Read examples in `/config/examples/`, test with `test_new_format.py`, check logs with `docker-compose logs`

# Custom Placeholders System

**Location**: `/config/custom_placeholders/`

**How it works**:
1. User creates `.py` files with placeholder functions
2. Functions execute in pipeline: unordered first, then by @order priority
3. Each function sees results from all previous executions
4. Results available as context keys in templates: `{{placeholder_name}}`

**Files reloaded**: Every 30 seconds (same as config rules)

**Two definition styles**:
```python
# Style 1: PLACEHOLDERS dict
PLACEHOLDERS = {
    'discount': calculate_discount,
}

# Style 2: @placeholder decorator with optional @order
from custom_placeholders import placeholder, order

@placeholder
def unordered_placeholder(context):
    return "value"

@order(10)
def ordered_placeholder(context):
    return "value"
```

**Execution order**:
1. Unordered placeholders first
2. @order(10) → @order(20) → @order(30+) in sequence

**Available in context**:
- `$.fieldName` - Message fields  
- `uuid`, `now`, `randomInt()` - Built-in functions
- `previous_placeholder_name` - Results from earlier stages
