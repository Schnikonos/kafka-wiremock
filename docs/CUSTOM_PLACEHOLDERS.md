# Custom Placeholders Guide

Custom placeholders let you define Python functions that generate or transform values during template rendering. They are loaded from `.py` files in `config/custom_placeholders/` (or any subdirectory) and support **hot-reload**.

## Overview

- Placeholder functions are called with the current **context dictionary** (extracted message fields, headers, etc.).
- Their return value is substituted wherever `{{myFunctionName}}` appears in a rule or test payload/header/key.
- Functions are executed in a **pipeline**: each function's result is added to the context so later functions can use earlier results.
- Files are scanned **recursively** — organise by subdirectory as you like.

## Directory Structure

```
config/
└── custom_placeholders/
    ├── business/
    │   ├── 10-business_logic.py   # Unordered (run first)
    │   └── 20-calculations.py     # Ordered (run after unordered)
    └── utils/
        └── formatting.py
```

Files are loaded in lexicographic order, but the execution order of the functions themselves is controlled by the `@order()` decorator (see below).

---

## Defining Placeholders

There are two ways to register placeholder functions.

### Method 1: `PLACEHOLDERS` Dictionary

Simple, no imports needed. All functions in the dict are registered automatically.

```python
# config/custom_placeholders/business/10-business_logic.py

def calculate_discount(context):
    """Calculate discount based on order amount."""
    try:
        amount = float(context.get('$.amount', 0))
        return round(amount * 0.1, 2) if amount > 1000 else 0.0
    except (ValueError, TypeError):
        return 0.0

def get_customer_tier(context):
    """Return customer tier (GOLD or STANDARD) based on customer ID."""
    customer_id = context.get('$.customerId', '')
    return 'GOLD' if customer_id.startswith('VIP') else 'STANDARD'

PLACEHOLDERS = {
    'discount': calculate_discount,
    'customer_tier': get_customer_tier,
}
```

### Method 2: `@placeholder` Decorator

More explicit; useful when you want to co-locate the registration with the function definition. Requires importing from `src.custom.placeholders`.

```python
# config/custom_placeholders/business/20-calculations.py
from src.custom.placeholders import placeholder, order

@placeholder
def final_price(context):
    """Calculate final price after applying discount."""
    amount = float(context.get('$.amount', 0))
    discount = float(context.get('discount', 0))  # Result from previous placeholder
    return round(amount - discount, 2)
```

---

## Execution Order

By default all unordered placeholders run first (in file/declaration order), then ordered ones in ascending `@order(n)` sequence.

```python
from src.custom.placeholders import placeholder, order

@placeholder                # No @order → runs first (unordered)
def final_price(context):
    ...

@placeholder
@order(20)                  # Runs after all unordered placeholders
def tier_discount(context):
    tier = context.get('customer_tier')   # Available because customer_tier ran first
    final = float(context.get('final_price', 0))
    return round(final * 0.05, 2) if tier == 'GOLD' and final > 500 else 0.0

@placeholder
@order(30)                  # Runs last
def total_with_tier_discount(context):
    final = float(context.get('final_price', 0))
    tier_disc = float(context.get('tier_discount', 0))
    return round(final - tier_disc, 2)
```

### Execution pipeline

```
Input message received
        │
        ▼
Context populated ($.field values, headers, etc.)
        │
        ▼
Unordered placeholders run (no @order)
        │  ← results added to context
        ▼
@order(20) placeholders
        │  ← results added to context
        ▼
@order(30) placeholders
        │  ← results added to context
        ▼
Template rendered with final context
```

---

## Using Placeholders in Rules

Reference custom placeholders by function name using `{{ ... }}` syntax:

```yaml
# config/rules/order-processing/01-order-created.yaml
priority: 10

when:
  topic: orders.input
  match:
    - type: jsonpath
      expression: "$.eventType"
      value: "ORDER_CREATED"

then:
  - topic: payments.input
    payload: |
      {
        "paymentId": "{{uuid}}",
        "orderId": "{{$.orderId}}",
        "originalAmount": "{{$.amount}}",
        "discount": "{{discount}}",
        "finalPrice": "{{final_price}}",
        "tierDiscount": "{{tier_discount}}",
        "totalAmount": "{{total_with_tier_discount}}",
        "customerTier": "{{customer_tier}}"
      }
```

---

## Context Reference

Custom placeholder functions receive a context dict with the following keys:

| Key | Description |
|-----|-------------|
| `$.fieldName` | JSON fields extracted from the input message via JSONPath |
| `full_message` | Raw input message as a string |
| `inputKey` | Input message key |
| `header.headerName` | Input message header values |
| `correlationId` | Extracted correlation ID (from topic-config) |
| `testId` | (Test runs only) Unique ID for the current test execution |
| `myPlaceholder` | Result of a previously-executed custom placeholder |

---

## Hot-Reload

Placeholder files are checked for changes automatically. When a file is added, removed, or modified, the registry is reloaded within the configured interval (default: 30 seconds).

---

## Installing Extra Dependencies

If your custom placeholder functions require third-party packages, place a `requirements.txt` in `config/python-requirements/`:

```
# config/python-requirements/requirements.txt
requests==2.31.0
boto3>=1.28
```

Kafka Wiremock automatically runs `pip install -r requirements.txt` when the file changes. Check installation status via:

```bash
curl http://localhost:8000/dependencies
```

---

## Listing Loaded Placeholders

```bash
curl http://localhost:8000/custom-placeholders | jq
```

Response:
```json
[
  { "name": "discount",                 "order": null, "docstring": "Calculate discount based on order amount." },
  { "name": "customer_tier",            "order": null, "docstring": "Return customer tier..." },
  { "name": "final_price",              "order": null, "docstring": "Calculate final price after applying discount." },
  { "name": "tier_discount",            "order": 20,   "docstring": "Calculate tier-based discount." },
  { "name": "total_with_tier_discount", "order": 30,   "docstring": "Final total after all discounts." }
]
```

---

## See Also

- [Rules Configuration](RULES.md) — how templates are used in rules
- [API Reference](API.md) — HTTP endpoints
