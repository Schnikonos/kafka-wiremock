# JSON Schema Reference

This directory contains JSON Schema (draft-07) files that validate every YAML configuration file used by Kafka Wiremock.  
Use them in your IDE for auto-complete and inline validation, or in CI/CD pipelines with any JSON Schema validator (`ajv`, `jsonschema`, …).

---

## Schema Overview

| Schema file | Validates | Config location |
|---|---|---|
| [`rule-schema.json`](#rule-schemajson) | Rule definitions | `config/rules/**/*.yaml` |
| [`topic-config-schema.json`](#topic-config-schemajson) | Kafka topic configuration | `config/topic-config/**/*.yaml` |
| [`jms-schema.json`](#jms-schemajson) | JMS queue-manager connections **and** per-destination config | `config/queue-managers.yaml` · `config/jms-config/**/*.yaml` |
| [`test-suite-schema.json`](#test-suite-schemajson) | Test suite definitions | `testSuite/**/*.test.yaml` |
| [`send-schema.json`](#send-schemajson) | Send (injection-only) definitions | `send/**/*.send.yaml` |

> **Deprecated files** – `jms-config-schema.json` and `jms-queue-config-schema.json` have been merged into `jms-schema.json`.  
> They still exist for backwards compatibility but point all definitions to the unified schema.

---

## Schema Details

### `rule-schema.json`

Validates a **single rule file** — one YAML file = one rule.

Rules live in `config/rules/` and can be organized in any subdirectory structure:

```
config/
└── rules/
    ├── order-processing/
    │   ├── 01-order-created.yaml   ← validated by rule-schema.json
    │   └── 02-order-shipped.yaml
    └── payments/
        └── 01-payment-received.yaml
```

A rule describes:
- **`when`** — which Kafka topic or JMS queue to listen on, and what conditions must match (`jsonpath`, `regex`, `exact`, `partial`)
- **`then`** — one or more output messages to produce (Kafka topic or JMS queue)
- Optional: `priority`, `skip`, `fault` injection, delays

---

### `topic-config-schema.json`

Validates a **Kafka topic configuration file**.  
Each file configures message format, schema-registry settings, and correlation-ID rules for one or more topics.

Files live in `config/topic-config/`:

```
config/
└── topic-config/
    ├── orders/
    │   └── 01-orders.yaml          ← validated by topic-config-schema.json
    └── payments/
        └── 01-payments.yaml
```

A topic-config describes:
- **`topic`** — Kafka topic name
- **`message.format`** — `json`, `avro`, `text`, or `bytes`
- **`schema_registry`** — Confluent Schema Registry subject and version (AVRO)
- **`correlation`** — how to extract and propagate correlation IDs

---

### `jms-schema.json`

Unified schema for **all JMS configuration**. A single file that validates two distinct YAML formats — the format is detected automatically by which top-level key is present:

#### Format 1 — Queue Managers file (`config/queue-managers.yaml`)

Contains a `queue_managers` key. Defines the broker connections that the application establishes at startup.  
Referenced by `queue_manager_ref` throughout rules, test suites, and jms-config files.

```
config/
└── queue-managers.yaml             ← validated by jms-schema.json (queueManagersFile)
```

Example:
```yaml
queue_managers:
  qm_dev_local:
    provider: ibm_mq
    broker_url: localhost(1414)
    channel: DEV.APP.SVRCONN
    queue_manager: QM1
    username: app_user

  qm_activemq:
    provider: activemq
    broker_url: localhost:61613
    username: admin

  qm_rabbit:
    provider: rabbitmq
    broker_url: localhost:5672
    username: guest
    virtual_host: /
```

Supported providers: `ibm_mq` · `activemq` · `rabbitmq`

Each queue manager entry also accepts an optional `pool` block — see [Connection Pooling](#connection-pooling) below.

#### Format 2 — Destination config files (`config/jms-config/**/*.yaml`)

Contains a `destination` key. Each file (or `---`-separated document) describes one JMS queue or topic: message format, JMS delivery properties, and correlation-ID rules.

```
config/
└── jms-config/
    ├── orders/
    │   └── 01-orders-input.yaml    ← validated by jms-schema.json (destinationConfig)
    └── payments/
        └── 01-payments-queue.yaml
```

Example:
```yaml
destination: ORDERS_INPUT
destination_type: queue
queue_manager_ref: qm_dev_local
provider: ibm_mq
message:
  format: json
jms_properties:
  persistence: true
  priority: 4
  expiry_ms: 0
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

#### Connection Pooling

Both queue-manager entries and the global JMS pool can be tuned via the `pool` block or environment variables:

```yaml
queue_managers:
  qm_dev_local:
    provider: ibm_mq
    # ... connection details ...
    pool:
      min_idle: 2
      max_size: 10
      max_wait_ms: 5000
      auto_reconnect: true
      reconnect_attempts: 3
      reconnect_delay_ms: 1000
      idle_timeout_ms: 900000
      max_lifetime_ms: 1800000
```

Global defaults can be set via `JMS_POOL_*` environment variables (see main README).

---

### `test-suite-schema.json`

Validates a **single test file** — one YAML file = one test.

Tests live in `testSuite/` and can be organized in subdirectories:

```
testSuite/
├── examples/
│   ├── 01-order-flow.test.yaml     ← validated by test-suite-schema.json
│   └── 02-payment-flow.test.yaml
└── regression/
    └── 01-smoke.test.yaml
```

A test describes:
- **`inject`** — messages to send before checking results (Kafka or JMS)
- **`expect`** — messages that must appear on specific topics/queues after the injection
- **`correlate`** — optional correlation-ID tracking across messages
- Optional: `skip`, `tags`, `fault` injection, delays

---

### `send-schema.json`

Validates a **single send file** — one YAML file = one send operation (injection without assertions).

Send files live in `send/` with the `.send.yaml` extension:

```
send/
├── examples/
│   ├── 01-send-orders.send.yaml    ← validated by send-schema.json
│   └── 04-send-jms-orders.send.yaml
└── load-tests/
    └── 01-high-volume.send.yaml
```

A send describes:
- **`inject`** — one or more messages to produce (Kafka topic or JMS queue, with optional delays)
- Optional: `name`, `tags`, `priority`, `skip`

---

## IDE Integration

### VS Code / Cursor

Add to your workspace settings (`.vscode/settings.json`):

```json
{
  "yaml.schemas": {
    "./json-schema/rule-schema.json":          "config/rules/**/*.yaml",
    "./json-schema/topic-config-schema.json":  "config/topic-config/**/*.yaml",
    "./json-schema/jms-schema.json":           ["config/queue-managers.yaml", "config/jms-config/**/*.yaml"],
    "./json-schema/test-suite-schema.json":    "testSuite/**/*.test.yaml",
    "./json-schema/send-schema.json":          "send/**/*.send.yaml"
  }
}
```

### JetBrains (IntelliJ / PyCharm)

Go to **Settings → Languages & Frameworks → Schemas and DTDs → JSON Schema Mappings** and add each schema with the corresponding file pattern.

---

## Command-Line Validation

Using [ajv-cli](https://github.com/ajv-validator/ajv-cli):

```bash
# Install once
npm install -g ajv-cli

# Validate a rule file
ajv validate -s json-schema/rule-schema.json -d config/rules/order-processing/01-order-created.yaml

# Validate queue-managers.yaml
ajv validate -s json-schema/jms-schema.json -d config/queue-managers.yaml

# Validate a JMS destination config
ajv validate -s json-schema/jms-schema.json -d config/jms-config/orders/01-orders-input.yaml
```

Using Python [jsonschema](https://python-jsonschema.readthedocs.io/):

```bash
pip install jsonschema pyyaml

python - <<'EOF'
import json, yaml, jsonschema, pathlib

schema = json.loads(pathlib.Path("json-schema/jms-schema.json").read_text())
data   = yaml.safe_load(pathlib.Path("config/queue-managers.yaml").read_text())
jsonschema.validate(data, schema)
print("Validation passed")
EOF
```

