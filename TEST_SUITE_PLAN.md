# **IMPLEMENTATION PLAN: Test Suite Feature for Kafka Wiremock**

**Document Version**: 1.0  
**Date**: April 6, 2026  
**Status**: Ready for Implementation (Plan Phase Complete)

---

## **Executive Summary**

The Test Suite feature adds integration testing capabilities to kafka-wiremock. Users can define test scenarios in YAML that inject messages (`when`), wait for expected outputs (`then`), and validate results via custom Python scripts. Tests run on-demand via API with support for sequential/parallel execution, statistics gathering, and future load testing.

**Key Design**: Reuses existing infrastructure (injector, consumer, matcher, templater, custom placeholders). Tests stored in `/testSuite/` directory, scanned on-demand. Message correlation via `source_id`/`target_id` fields.

---

## **Architecture & Components**

### **1. New File: `src/test_suite.py`**
**Purpose**: Core test orchestration engine

**Main Classes**:
- `TestDefinition` — Dataclass for parsed test YAML (mirrors `Rule` pattern)
  - Fields: `name`, `priority`, `skip`, `when` (injections + script), `then` (expectations + script)
- `TestInjection` — Individual message to inject with correlation ID
- `TestExpectation` — Expected message to receive with optional match conditions
- `TestResult` — Result of single test execution (passed/failed, elapsed_ms, errors)
- `TestSuiteRunner` — Orchestrates test execution (sequential/parallel modes)
- `TestResultAggregator` — Collects and formats results for bulk runs

**Key Methods**:
```python
# Parse and discover tests
def load_tests_from_directory(testSuite_dir: str) -> List[TestDefinition]
def discover_then_topics(tests: List[TestDefinition]) -> Set[str]

# Execution
async def run_test(test: TestDefinition, context: Dict) -> TestResult
async def run_tests_sequential(tests: List[TestDefinition]) -> List[TestResult]
async def run_tests_parallel(tests: List[TestDefinition], threads: int) -> List[TestResult]

# Result aggregation
def aggregate_results(results: List[TestResult], mode: str) -> Dict
```

---

### **2. New File: `src/test_loader.py`**
**Purpose**: YAML parsing and validation for test files

**Main Classes**:
- `TestYamlParser` — Parses test YAML, validates structure
- `TestValidator` — Validates test semantics (required fields, correlation IDs, etc.)

**Key Methods**:
```python
def parse_test_yaml(yaml_content: str) -> Dict
def validate_test_definition(test_dict: Dict) -> TestDefinition
def validate_correlation_ids(test: TestDefinition) -> List[str]  # Warnings/errors
```

---

### **3. New File: `src/test_consumer_manager.py`**
**Purpose**: Pre-start Kafka consumers for test output topics (avoids 4-5s startup delay)

**Key Logic**:
- Scans test files periodically (e.g., every 30s, same as rules/placeholders)
- Detects new `then` topics
- Pre-creates consumers for those topics (non-blocking)
- Retries consumer creation if topic doesn't exist yet
- Maintains consumer pool in background thread

**Main Classes**:
- `TestConsumerManager` — Manages consumer lifecycle and pooling

**Key Methods**:
```python
def start(self)
def stop(self)
def discover_and_start_consumers(tests: List[TestDefinition])  # Called periodically
def get_consumer_for_topic(topic: str) -> Optional[KafkaConsumer]
def pre_warm_consumers()  # Run on startup
```

---

### **4. Update `src/main.py`**
**Add Endpoints**:
```python
@app.post("/tests/{test_id}")
async def run_single_test(test_id: str) -> Dict
    # Run one test, return result

@app.post("/tests:bulk")
async def run_tests_bulk(
    mode: str = Query("parallel"),  # sequential, parallel
    threads: int = Query(4),
    iterations: int = Query(10),
    filter_tags: Optional[List[str]] = None  # Optional tag filtering
) -> Dict
    # Run all discovered tests, return aggregated results

@app.get("/tests")
async def list_tests() -> List[Dict]
    # List all discovered tests with metadata

@app.get("/tests/{test_id}")
async def get_test_definition(test_id: str) -> Dict
    # Get parsed test YAML
```

---

## **Test File Format Specification**

**Location**: `/testSuite/` (any subdirectories supported)  
**Naming**: `*.test.yaml` or `*.test.yml` (explicit; distinguishes from rules)

**Structure**:
```yaml
# Metadata
priority: 10                    # Optional; default 999 (last). Lower = runs first
name: "order-to-payment-flow"   # Required; test ID derived from filename or this field
tags: ["critical", "e2e"]       # Optional; for filtering
skip: false                     # Optional; default false

timeout_ms: 5000               # Optional; default 2000. Overall test timeout

# Input phase: Inject messages
when:
  inject:
    - message_id: "order1"      # Required; used for correlation
      topic: "orders.input"     # Required
      payload: |
        {
          "orderId": "{{testId}}-{{uuid}}",
          "amount": 100.50,
          "customerId": "CUST-123"
        }
      headers:                  # Optional; same as rules
        X-Request-ID: "{{uuid}}"
      delay_ms: 0              # Optional; delay before injection
    
    - message_id: "notification1"
      topic: "notifications.input"
      payload: '{"type": "order_created", "orderId": "{{testId}}-{{uuid}}"}'
  
  script: |                     # Optional; Python code executed after injections
    # Pre-conditions, DB setup, etc.
    # Context has: injected[] (list of injected messages with their payloads)
    # Can access custom placeholders: custom_placeholders["name"]
    # Can raise exceptions to fail test
    assert len(injected) == 2, "Expected 2 injected messages"
    print(f"Injected {len(injected)} messages")

# Output phase: Expect messages
then:
  expectations:
    - source_id: "order1.orderId"   # Optional; correlate from injected message
                                    # Format: "message_id.jsonpath_to_field"
                                    # If not provided, any message matching conditions = OK
      target_id: "$.orderId"        # Optional; field in received message to match source_id
                                    # Can also reference headers: "$.headers.X-Order-ID"
      topic: "payments.input"       # Required
      wait_ms: 2000                 # Optional; default 2000. Max time to wait for this message
      match:                        # Optional; additional validation
        - type: jsonpath
          expression: "$.amount"
          value: 100.50
        - type: jsonpath
          expression: "$.status"
          regex: "PENDING|CONFIRMED"
  
  script: |                     # Optional; Python code executed after message collection
    # Custom validation, assertions, side effects
    # Context has: injected[], received[] (messages per expectation), stats{}
    # Can raise exceptions to fail test
    assert len(received) >= len(expectations), "Not all expected messages received"
    for msg in received:
      assert msg['amount'] > 0, f"Invalid amount in {msg}"
```

**Key Points**:
- `source_id` format: `"message_id.$.jsonpath_expression"` or just `"message_id"` (use full payload)
- `target_id` format: `"$.jsonpath"` or `"$.headers.header_name"` to match source
- If `source_id`/`target_id` not specified: **Accept any message matching conditions** (or any message if no conditions)
- Match conditions reuse existing `Condition` class and `MatcherFactory`
- Custom scripts raise exceptions on failure (no return value needed)

---

## **Message Correlation Algorithm**

```
For each expectation:
  1. Resolve source_id:
     - If "message_id.$.field": Extract value from injected[message_id].payload using JSONPath
     - If "message_id": Use full injected message as correlation key
     - If not provided: No correlation (match any message by topic + conditions)

  2. Collect received messages:
     - Poll topic for up to wait_ms seconds
     - For each received message:
       - If target_id specified:
         - Extract value using target_id JSONPath (or header)
         - If matches source_id value AND conditions match: ACCEPT
       - Else:
         - If conditions match (or no conditions): ACCEPT

  3. Check satisfaction:
     - If source_id was used: Expect exactly 1 matching message
     - Else: Expect at least 1 message matching conditions
       (Multiple messages could match; that's OK)
```

---

## **Execution Flow & Context Building**

### **When Phase**:
1. Parse injections
2. Render templates (custom placeholders, built-ins)
3. Produce messages to Kafka
4. Capture injected payloads (for context)
5. Execute `when` script (if present)
   - Exception raised → **Test FAILS immediately**

### **Wait Phase**:
1. For each expectation, poll target topic for up to `wait_ms`
2. Correlate received messages using `source_id`/`target_id`
3. Apply match conditions
4. Collect matching messages

### **Then Phase**:
1. Execute `then` script (if present)
   - Context includes: `injected[]`, `received[]` (dict with messages per expectation), `stats{}`
   - Exception raised → **Test FAILS**
2. Validate all expectations satisfied (at least one matching message)

---

## **Custom Script Execution Context**

### **When Script Context**:
```python
{
    "injected": [
        {
            "message_id": "order1",
            "topic": "orders.input",
            "payload": {"orderId": "...", ...},  # Parsed JSON or string
            "timestamp": 1712419200000
        },
        ...
    ],
    "custom_placeholders": {
        "my_custom_func": <result>,  # From /config/custom_placeholders/
        ...
    },
    # Built-in functions available in scope:
    # uuid, now, randomInt(min, max)
    "kafka_client": <KafkaClientWrapper>,  # For direct access if needed
}
```

### **Then Script Context**:
```python
{
    "injected": [
        {"message_id": "order1", "topic": "...", "payload": {...}, ...}
    ],
    "received": {
        "expectation_0": [
            {
                "topic": "payments.input",
                "value": {"amount": 100.50, ...},
                "timestamp": 1712419201000,
                "partition": 0,
                "offset": 12345,
                "headers": {...}
            },
            ...
        ]
    },
    "stats": {
        "elapsed_ms": 234,  # Total elapsed for this test
        "expectation_0_elapsed_ms": 150  # Per expectation
    },
    "custom_placeholders": {...},
    "kafka_client": <KafkaClientWrapper>,
}
```

---

## **Test Result Format**

### **Single Test Result**:
```json
{
    "test_id": "order-flow-test",
    "status": "PASSED",  // or FAILED, SKIPPED, TIMEOUT
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
                "received_messages": [
                    {
                        "value": {"amount": 100.50, "status": "PENDING"},
                        "timestamp": 1712419201000
                    }
                ]
            }
        ],
        "script_error": null
    },
    "errors": []  // If any, test is FAILED
}
```

### **Bulk Run Result (Summary)**:
```json
{
    "mode": "parallel",
    "threads": 4,
    "iterations": 10,
    "total_tests": 30,  // 3 tests × 10 iterations
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
        },
        ...
    },
    "failed_tests": [
        {
            "test_id": "order-flow-test",
            "iteration": 6,
            "error": "Expectation failed for payments.input: timeout waiting for message",
            "logs": [...]  // Last N log lines for context
        }
    ]
}
```

---

## **Test Discovery & Consumer Pre-warming**

### **Test Discovery**:
1. **On-Demand**: Scan `/testSuite/` when API endpoint called
2. **Periodic Scan**: Background thread periodically checks for new/modified `*.test.yaml` files
   - Tracks file hashes (same as rules/placeholders)
   - On change: Notify `TestConsumerManager` of new topics

### **Consumer Pre-warming** (New Background Thread):
```
Every 30 seconds:
  1. Discover all tests in /testSuite/
  2. Extract all 'then' topics
  3. For each topic:
     - If consumer doesn't exist: Try to create
     - If topic doesn't exist: Log warning, retry next cycle
     - If consumer created: Pre-start polling (warm cache)
  4. Clean up consumers for topics no longer in any test
```

**Why**: Kafka consumers take 4-5s to start. Pre-warming avoids delays during test execution.

---

## **Implementation Sequence**

**Phase 1: Core Infrastructure**
1. `test_loader.py` — Parse/validate test YAML
2. `test_suite.py` — Test execution logic (single test, sequential/parallel modes)
3. Update `main.py` — Add endpoints
4. Add test discovery to main startup

**Phase 2: Consumer Management**
5. `test_consumer_manager.py` — Pre-warm consumers, periodic scanning

**Phase 3: Integration & Testing**
6. Unit tests for test_loader, test_suite
7. Integration tests with live Kafka
8. Example test files in `/config/testSuite/examples/`

**Phase 4: Future (Load Testing)**
- Extend `TestSuiteRunner` with load mode
- Add metrics collection (throughput, latency percentiles)
- Support test parameterization (variations)

---

## **Key Design Decisions**

| Decision | Rationale |
|----------|-----------|
| **Dedicated `/testSuite/` dir** | Clear separation from rules; avoids confusion |
| **`*.test.yaml` naming** | Explicit; easy to scan and distinguish |
| **On-demand discovery** | Tests are ephemeral; no need for hot-reload |
| **Priority + ordering optional** | Flexibility; undefined order acceptable |
| **source_id/target_id correlation** | Simpler than full payload matching; JSON-path flexible |
| **Exception-based failures** | Pythonic; easier for users to write assertions |
| **Pre-warm consumers** | Avoids 4-5s startup delay during test runs |
| **Summary stats for bulk** | Detailed logs separate; API response focused on overview |
| **No topic creation** | Safer; tests assume topics exist (like rules) |

---

## **Future Enhancements (Post-MVP)**

1. **Load Testing** — API parameter to repeat tests N times with metrics
2. **Test Parameterization** — Matrix testing (e.g., 10 different order amounts)
3. **Test Dependencies** — Test B uses outputs from test A
4. **Scheduling** — Cron-like periodic test execution
5. **Test Reporting** — HTML reports, CI/CD integration
6. **Chaos Injection** — Simulate failures in test scenarios

---

## **Error Handling & Logging**

**Test Execution Errors**:
- **YAML Parse Error** → Return 400 with error message
- **Missing Topics** → Test runs but expectations timeout
- **Script Exception** → Test FAILS; exception message in results
- **Kafka Connection Error** → Return 503; log error

**Logging**:
- Log level: INFO for test progress, DEBUG for message details
- Test logs include: Injections, expectations, script output, correlations
- Failed tests log: Full received messages, assertion errors, stack traces

---

## **Configuration & Environment Variables**

**New Env Vars** (optional):
```bash
TEST_SUITE_DIR=/testSuite              # Default if not exists
TEST_CONSUMER_POOL_SIZE=20             # Max consumers to maintain
TEST_DISCOVERY_INTERVAL=30             # Scan interval (seconds)
```

---

## **Testing Strategy**

**Unit Tests** (`tests/test_test_suite.py`):
- YAML parsing and validation
- Correlation ID extraction
- Result aggregation
- Custom script execution (mocked Kafka)

**Integration Tests**:
- End-to-end test execution with live Kafka
- Consumer pre-warming behavior
- Parallel execution correctness
- Message correlation across multiple expectations

**Example Tests** (`/testSuite/examples/`):
- Simple single injection → single expectation
- Multiple injections with correlation
- Load test readiness (can be parameterized later)

---

## **Summary Table**

| Component | Status | Purpose |
|-----------|--------|---------|
| Test discovery | ✓ Designed | On-demand scan of `/testSuite/` for `*.test.yaml` files |
| YAML parsing | ✓ Designed | Parse test definitions, validate structure |
| Message correlation | ✓ Designed | `source_id`/`target_id` linking injected→expected |
| Single test execution | ✓ Designed | Inject → Wait → Validate → Report |
| Parallel execution | ✓ Designed | Concurrent test runs with thread pool |
| Custom scripts | ✓ Designed | Exception-based validation with full context |
| Consumer pre-warming | ✓ Designed | Background thread pre-starts consumers for test topics |
| Results/Stats | ✓ Designed | Per-test + aggregated metrics |
| API Endpoints | ✓ Designed | `/tests`, `/tests/{id}`, `/tests:bulk` |
| Load testing | ⏳ Deferred | Future enhancement (architecture supports it) |

