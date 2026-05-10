# Custom validation script for payment expectation
# This script runs after payment messages are collected from the output topic

import json

# Access to context:
# - injected: All injected messages from when phase
# - received: Dictionary of collected messages per expectation
# - previous_expectations: Results of earlier expectations
# - current_expectation: The result of current expectation collection
# - custom_placeholders: Available placeholders
# - context: Values contributed by previous scripts

# Check if we got the expected payment
payments = received.get(0, [])  # expectation_0
assert len(payments) >= 1, f"Expected at least 1 payment, got {len(payments)}"

payment = payments[0].get("value", {})
if isinstance(payment, str):
    payment = json.loads(payment)

# Use context from injection script
expected_amount = context.get("order_amount")
actual_amount = payment.get("amount")

assert actual_amount == expected_amount, \
    f"Payment amount mismatch: expected ${expected_amount}, got ${actual_amount}"

# Validate payment status
assert payment.get("status") in ["PENDING", "CONFIRMED"], \
    f"Invalid payment status: {payment.get('status')}"

print(f"✓ Payment validated: ${actual_amount} ({payment.get('status')})")

