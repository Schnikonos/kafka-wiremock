# Custom validation script for order injection
# This script runs after an order is injected and validates/processes it

import json

# Access to context from test execution:
# - injected: List of all injected messages so far
# - previous_injections: List of injected messages before this one
# - current_injection: The message that was just injected
# - custom_placeholders: Available placeholders
# - kafka_client: Kafka client for direct access if needed
# - context: Dictionary to store values for later use

# Validate the injected order
order = current_injection.get("payload", {})
if isinstance(order, str):
    order = json.loads(order)

assert "orderId" in order, "Order must have orderId"
assert "amount" in order, "Order must have amount"
assert order.get("amount", 0) > 0, "Order amount must be positive"

# Extract order ID for later use
order_id = order.get("orderId")

# Contribute to context for later expectations to use
context["order_id"] = order_id
context["order_amount"] = order.get("amount")

print(f"✓ Order validated: {order_id} (${order.get('amount')})")

