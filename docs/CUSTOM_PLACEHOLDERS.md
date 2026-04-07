# Custom Placeholders Guide

Custom placeholders allow you to extend Kafka Wiremock with user-defined functions for complex logic, data transformations, and business rule implementation.

## Overview

Custom placeholders are Python functions defined in `/config/custom_placeholders/` that execute in a **pipeline**. Each placeholder:
- Receives context from message fields and previous placeholders
- Returns a value available as `{{placeholder_name}}` in templates
- Executes in a defined order (unordered first, then by @order priority)
- Is hot-reloaded every 30 seconds

## Directory Structure

```
config/
├── custom_placeholders/
│   ├── business/
│   │   ├── 10-discounts.py
│   │   └── 20-pricing.py
│   ├── integrations/
│   │   └── 30-external-apis.py
│   └── 10-business_logic.py
```

Files are scanned **recursively** - organize by subdirectories as your project grows!

## Defining Placeholders

### Method 1: PLACEHOLDERS Dict

Define a dictionary mapping placeholder names to functions:

```python
# /config/custom_placeholders/10-business_logic.py

def calculate_discount(context):
    """Calculate discount based on amount"""
    amount = float(context.get('$.amount', 0))
    return amount * 0.1 if amount > 1000 else 0.0

def get_customer_tier(context):
    """Fetch customer tier from context"""
    customer_id = context.get('$.customerId', 'UNKNOWN')
    tiers = {'C1': 'GOLD', 'C2': 'SILVER'}
    return tiers.get(customer_id, 'BRONZE')

PLACEHOLDERS = {
    'discount': calculate_discount,
    'customer_tier': get_customer_tier,
}
```

### Method 2: @placeholder Decorator

Use decorators for cleaner syntax:

```python
# /config/custom_placeholders/20-calculations.py

from custom_placeholders import placeholder, order

@placeholder
def calculate_tax(context):
    """Calculate tax on amount"""
    amount = float(context.get('$.amount', 0))
    return amount * 0.08

# With execution order
@order(10)
@placeholder
def final_price(context):
    """Calculate final price including discount"""
    amount = float(context.get('$.amount', 0))
    discount = float(context.get('discount', 0))  # From stage 1
    return amount - discount

@order(20)
@placeholder
def total_with_tax(context):
    """Add tax to final price"""
    final = float(context.get('final_price', 0))  # From @order(10)
    tax = float(context.get('calculate_tax', 0))  # From stage 1
    return final + tax
```

## Execution Order

Placeholders execute in a precise pipeline:

1. **Unordered stage** - All placeholders without `@order` decorator
2. **Ordered stages** - Placeholders with `@order`, sorted by order number (10, 20, 30, ...)

Each stage sees all results from previous stages.

### Example Pipeline

```python
# Stage 1: Unordered
@placeholder
def discount(context):
    return float(context.get('$.amount', 0)) * 0.1

@placeholder  
def tax_rate(context):
    return 0.08

# Stage 2: @order(10)
@order(10)
@placeholder
def final_price(context):
    amount = float(context.get('$.amount', 0))
    disc = float(context.get('discount', 0))  # From stage 1
    return amount - disc

# Stage 3: @order(20)
@order(20)
@placeholder
def total_with_tax(context):
    final = float(context.get('final_price', 0))  # From stage 2
    tax_rate = float(context.get('tax_rate', 0))  # From stage 1
    return final * (1 + tax_rate)
```

Execution order:
1. `discount()` and `tax_rate()` (unordered)
2. `final_price()` (@order(10))
3. `total_with_tax()` (@order(20))

## Available Context

Functions receive a `context` dictionary with access to:

### Message Fields

Extract values from the incoming message using JSONPath:

```python
@placeholder
def extract_customer_id(context):
    # context['$.customerId'] - Extract from message
    customer_id = context.get('$.customerId', 'UNKNOWN')
    return customer_id.upper()
```

### Built-in Placeholders

Access built-in values:

```python
@placeholder
def create_event_id(context):
    # Built-in functions available
    uuid_val = context.get('uuid', '')  # UUID v4
    timestamp = context.get('now', '')   # Current timestamp
    return f"{uuid_val}_{timestamp}"
```

### Previous Placeholder Results

Access results from earlier stages:

```python
@order(20)
@placeholder
def final_amount(context):
    # Stage 1 results available
    discount = float(context.get('discount', 0))
    base_amount = float(context.get('$.amount', 0))
    
    # See stage 2 if combined
    if 'initial_price' in context:
        return context.get('initial_price', base_amount)
    
    return base_amount - discount
```

## Real-World Examples

### Example 1: Dynamic Pricing

```python
# /config/custom_placeholders/pricing.py

@placeholder
def base_price(context):
    """Extract base price from message"""
    return float(context.get('$.price', 0))

@placeholder
def volume_discount(context):
    """Apply volume discount"""
    quantity = int(context.get('$.quantity', 1))
    if quantity >= 100:
        return 0.20  # 20% discount
    elif quantity >= 50:
        return 0.10  # 10% discount
    return 0.05      # 5% base discount

@order(10)
@placeholder
def discounted_price(context):
    """Calculate discounted price"""
    base = float(context.get('base_price', 0))
    discount_rate = float(context.get('volume_discount', 0.05))
    return base * (1 - discount_rate)

@order(20)
@placeholder
def final_with_tax(context):
    """Apply tax to final price"""
    price = float(context.get('discounted_price', 0))
    tax_rate = 0.08
    return round(price * (1 + tax_rate), 2)

PLACEHOLDERS = {
    'base_price': base_price,
    'volume_discount': volume_discount,
    'discounted_price': discounted_price,
    'final_with_tax': final_with_tax,
}
```

Usage in rules:

```yaml
then:
  - topic: orders.processed
    payload: |
      {
        "orderId": "{{$.orderId}}",
        "basePrice": {{base_price}},
        "discount": {{volume_discount}},
        "finalPrice": {{discounted_price}},
        "totalWithTax": {{final_with_tax}}
      }
```

### Example 2: External Integration

```python
# /config/custom_placeholders/integrations.py

import requests
from custom_placeholders import order, placeholder

@placeholder
def validate_customer(context):
    """Check if customer is valid"""
    customer_id = context.get('$.customerId')
    try:
        # Call external service
        resp = requests.get(f"http://api.example.com/customers/{customer_id}")
        return resp.status_code == 200
    except:
        return False

@order(10)
@placeholder
def customer_status(context):
    """Get customer status if valid"""
    is_valid = context.get('validate_customer', False)
    if is_valid:
        customer_id = context.get('$.customerId')
        # Could fetch additional data
        return "VERIFIED"
    return "UNVERIFIED"

PLACEHOLDERS = {
    'validate_customer': validate_customer,
    'customer_status': customer_status,
}
```

### Example 3: Multi-Stage Processing

```python
# /config/custom_placeholders/order_processing.py

from custom_placeholders import order, placeholder

# Stage 1: Extract and validate
@placeholder
def order_type(context):
    order_type = context.get('$.type', 'STANDARD').upper()
    return order_type if order_type in ['STANDARD', 'EXPRESS', 'OVERNIGHT'] else 'STANDARD'

@placeholder
def shipping_cost(context):
    amount = float(context.get('$.amount', 0))
    return 0 if amount > 100 else 10

# Stage 2: Calculate intermediate values
@order(10)
@placeholder
def subtotal_shipped(context):
    amount = float(context.get('$.amount', 0))
    shipping = float(context.get('shipping_cost', 0))
    return amount + shipping

# Stage 3: Final calculations
@order(20)
@placeholder
def final_amount(context):
    subtotal = float(context.get('subtotal_shipped', 0))
    tax_rate = 0.08
    return round(subtotal * (1 + tax_rate), 2)

PLACEHOLDERS = {
    'order_type': order_type,
    'shipping_cost': shipping_cost,
    'subtotal_shipped': subtotal_shipped,
    'final_amount': final_amount,
}
```

## Best Practices

1. **Keep functions pure** - No side effects, consistent output for same input
2. **Handle missing context** - Use `.get()` with defaults
3. **Type conversions carefully** - Validate before converting to int/float
4. **Return simple types** - Strings, numbers, booleans work best
5. **Document assumptions** - Explain what context fields are expected
6. **Test locally** - Create test scripts before deploying
7. **Use @order sparingly** - Most placeholders work unordered
8. **Avoid long-running ops** - External calls should have timeouts

## Error Handling

Placeholders that raise exceptions are logged but don't fail the rule:

```python
@placeholder
def safe_division(context):
    try:
        numerator = float(context.get('$.numerator', 0))
        denominator = float(context.get('$.denominator', 1))
        return numerator / denominator if denominator != 0 else 0
    except Exception as e:
        # Logged as warning, returns None
        return None
```

Missing placeholders in templates are substituted with the placeholder text itself:

```yaml
payload: |
  {
    "value": "{{missing_placeholder}}"  # Outputs: "{{missing_placeholder}}"
  }
```

## Hot-Reload

Placeholder files are reloaded every 30 seconds:

- New files are automatically discovered
- Modified files are reloaded (changes take effect)
- Deleted files are removed
- No service restart required

## Debugging

Access placeholders via API:

```bash
curl http://localhost:8000/custom-placeholders
```

Response:
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
  }
]
```

Check logs for placeholder errors:

```bash
docker-compose logs kafka-wiremock | grep -i placeholder
```

## See Also

- [Rules Configuration Guide](RULES.md)
- [API Reference](API.md)

