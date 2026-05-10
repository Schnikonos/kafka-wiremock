# JMS Support Guide

IBM Message Queue (JMS) integration for Kafka Wiremock enables testing with message-oriented middleware systems alongside or instead of Kafka.

## Overview

Kafka Wiremock now supports dual messaging systems:
- **Kafka Topics** - For event streaming architecture
- **JMS Queues** - For enterprise message queues (IBM MQ, etc.)

Rules can mix inputs and outputs across both systems:
- Kafka → Kafka
- JMS → JMS
- Kafka → JMS
- JMS → Kafka

## Installation

### 1. Install IBM MQ Python Client (Optional)

The JMS implementation uses IBM MQ's Python client library. This is optional and not included in the default requirements.txt since it requires access to IBM's private repository.

```bash
# IBM MQ Python client requires IBM's repository
# Install from IBM's public repository:
pip install ibm-mq --index-url https://public.dhe.ibm.com/ibmdl/export/pub/software/websphere/messaging/mqpython/

# For authentication and more details, see:
# https://www.ibm.com/docs/en/ibm-mq/latest?topic=mqtt-ibm-mq-python-client

# System dependencies may also be needed (varies by OS)
# Ubuntu/Debian:
sudo apt-get install ibmmq-client
```

### 2. Configure IBM MQ Connection

Set environment variables before starting the application:

```bash
export IBM_MQ_BROKER_URL="localhost(1414)"
export IBM_MQ_CHANNEL="DEV.APP.SVRCONN"
export IBM_MQ_QUEUE_MANAGER="QM1"
export IBM_MQ_USERNAME="mqm"
export IBM_MQ_PASSWORD="your-password"

# Optional: SSL/TLS configuration
export IBM_MQ_SSL_KEY_STORE="/path/to/keystore.pem"
export IBM_MQ_SSL_KEY_STORE_PASSWORD="keystore-password"
```

### 3. Docker Compose (with IBM MQ)

Add IBM MQ to your docker-compose.yml:

```yaml
version: '3.8'
services:
  ibmmq:
    image: icr.io/ibm-messaging/mq:latest
    ports:
      - "1414:1414"
      - "9443:9443"
    environment:
      LICENSE: accept
      MQ_QMGR_NAME: QM1
    volumes:
      - mq-data:/mnt/mqm

  kafka-wiremock:
    build: ./kafka-wiremock
    depends_on:
      - ibmmq
      - kafka
    ports:
      - "8000:8000"
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      IBM_MQ_BROKER_URL: ibmmq(1414)
      IBM_MQ_CHANNEL: DEV.APP.SVRCONN
      IBM_MQ_QUEUE_MANAGER: QM1
      IBM_MQ_USERNAME: app
      IBM_MQ_PASSWORD: password

volumes:
  mq-data:
```

## Configuration

### JMS Queue Configuration

Create YAML files in `config/jms-config/` to define queue properties:

```yaml
# config/jms-config/orders-input.yaml

destination: ORDERS_INPUT
destination_type: queue  # 'queue' or 'topic'

message:
  format: json  # json, avro, text, bytes

jms_properties:
  persistence: true
  priority: 4
  time_to_live: 86400000  # milliseconds

correlation:
  extract:
    - from: header
      name: X-Correlation-Id
      priority: 1
    - from: jsonpath
      expression: $.correlationId
      priority: 2
  
  propagate:
    to_headers:
      X-Correlation-Id: "{{correlationId}}"
```

**Configuration Options:**

| Field | Type | Description |
|-------|------|-------------|
| `destination` | string | Queue or topic name (required) |
| `destination_type` | string | `queue` or `topic` (default: queue) |
| `message.format` | string | Message format: json, avro, text, bytes |
| `jms_properties` | object | Custom JMS message properties |
| `correlation` | object | Correlation ID extraction and propagation |

### Rule Configuration with msg_type

Rules now support the `msg_type` field to specify message source and destination:

```yaml
# config/rules/jms-to-kafka.yaml

priority: 10
name: "process-jms-order"

when:
  topic: ORDERS_INPUT
  msg_type: jms  # Input from JMS queue
  match:
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CREATED"

then:
  # Route to Kafka
  - topic: orders.created
    msg_type: kafka
    payload: |
      {
        "orderId": "{{$.orderId}}",
        "source": "jms",
        "timestamp": "{{now}}"
      }
  
  # Also notify another JMS queue
  - topic: ORDERS_NOTIFICATION
    msg_type: jms
    delay_ms: 100
    payload: |
      {
        "orderId": "{{$.orderId}}",
        "notification": "Order created"
      }
```

**Rule Fields:**

```yaml
when:
  topic: QUEUE_OR_TOPIC_NAME        # JMS queue name or Kafka topic
  msg_type: jms                     # 'kafka' or 'jms' (default: kafka)
  match:                            # Matching conditions (same as Kafka)
    - type: jsonpath
      expression: "$.field"
      value: "expected"

then:
  - topic: OUTPUT_NAME              # Output queue/topic name
    msg_type: jms                   # 'kafka' or 'jms' (default: kafka)
    payload: |                      # Message template (required)
      {...}
    delay_ms: 100                   # Delay before sending (optional)
    headers: {}                     # Custom headers (optional)
    fault: {}                       # Fault injection (optional)
```

## API Usage

### Inject Messages

```bash
# Inject to JMS queue
curl -X POST "http://localhost:8000/api/inject/ORDERS_INPUT?msg_type=jms" \
  -H "Content-Type: application/json" \
  -d '{
    "orderId": "ORD-123",
    "eventType": "ORDER_CREATED",
    "amount": 99.99
  }'

# Response
{
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "topic": "ORDERS_INPUT",
  "status": "success"
}
```

### Consume Messages

```bash
# Get messages from JMS queue
curl "http://localhost:8000/api/messages/ORDERS_PROCESSED?msg_type=jms&limit=10"

# Response
[
  {
    "value": {
      "orderId": "ORD-123",
      "status": "processed"
    },
    "format": "json",
    "timestamp": 1694721600000,
    "offset": 0,
    "partition": 0,
    "key": null,
    "headers": {}
  }
]
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `msg_type` | string | `kafka` | Message type: `kafka` or `jms` |
| `limit` | integer | 10 | Maximum messages to retrieve (max: 100) |
| `timeout_ms` | integer | 500 | Polling timeout in milliseconds |
| `poll_interval_ms` | integer | 100 | Poll interval (Kafka only) |

## Testing with JMS

### Example: Test Suite with JMS

```yaml
# testSuite/examples/jms-order-test.yaml

priority: 10
name: "jms-order-flow-test"
tags: ["jms", "orders"]
timeout_ms: 5000

when:
  inject:
    # Inject to JMS queue
    - message_id: "order1"
      topic: ORDERS_INPUT
      msg_type: jms  # Specify JMS as input
      payload: |
        {
          "orderId": "ORD-123",
          "eventType": "ORDER_CREATED",
          "amount": 99.99
        }

then:
  expectations:
    # Expect output on Kafka topic
    - topic: orders.created
      msg_type: kafka
      wait_ms: 2000
      correlate:
        message_id: "order1"
      match:
        - type: jsonpath
          expression: "$.orderId"
          value: "ORD-123"
    
    # Also expect output on JMS queue
    - topic: ORDERS_NOTIFICATION
      msg_type: jms
      wait_ms: 1000
      correlate:
        message_id: "order1"
      match:
        - type: jsonpath
          expression: "$.notification"
          value: "Order created"
```

## Troubleshooting

### IBM MQ Connection Issues

**Error: "MQ connection failed"**
- Verify IBM MQ service is running
- Check broker URL and port (default: `localhost(1414)`)
- Verify credentials (username/password)
- Check queue manager name matches

**Error: "Queue not found"**
- Verify queue exists in IBM MQ
- Check queue name spelling (case-sensitive)
- Verify user has permissions to access queue

### Message Format Issues

**Error: "Failed to deserialize message"**
- Check message format in JMS config matches actual message
- Verify JSON is valid if using `format: json`
- Check character encoding (UTF-8 expected)

### JMS Library Issues

**Error: "ibm-mq module not found"**
```bash
# Install IBM MQ from IBM's repository
pip install ibm-mq --index-url https://public.dhe.ibm.com/ibmdl/export/pub/software/websphere/messaging/mqpython/
```

**Error: "IBM MQ C libraries not found"**
- Install IBM MQ client libraries (system-level)
- Ensure MQ_INSTALL_PATH is set if needed

## Performance Considerations

### Message Throughput
- JMS queues typically process 1,000-5,000 msg/sec
- Kafka topics can handle 10,000+ msg/sec
- Use Kafka for high-volume streams
- Use JMS for transactional, persistent requirements

### Queue Depth
- Monitor queue depth to prevent overflow
- Configure dead letter queues for failed messages
- Implement message TTL (time-to-live) in JMS properties

### Correlation Handling
- JMS properties are used for headers
- Correlation IDs are propagated automatically if configured
- Use same correlation key names across systems for tracing

## Limitations

- **Message Size**: JMS messages limited by queue manager (typically 100MB)
- **Persistence**: JMS is persistent by default, Kafka can be configured
- **Partitioning**: JMS doesn't have partitions like Kafka
- **Consumer Groups**: JMS uses point-to-point or publish-subscribe
- **Schema Registry**: AVRO currently works better with Kafka

## See Also

- [API Reference](API.md) - Full API documentation
- [RULES.md](RULES.md) - Rule syntax and examples
- [TEST_SUITE.md](TEST_SUITE.md) - Integration testing guide
- [IBM MQ Documentation](https://www.ibm.com/docs/en/ibm-mq)

