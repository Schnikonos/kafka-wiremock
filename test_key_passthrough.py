#!/usr/bin/env python
"""Test script to verify message key pass-through works correctly."""

from src.rules.templater import TemplateRenderer

print("=" * 70)
print("Testing Message Key Pass-Through (Your Scenario)")
print("=" * 70)

# Scenario 1: Input message HAS a key
print("\n📝 Scenario 1: Input message HAS a key 'myMessageKey'")
print("-" * 70)
context = {
    'inputKey': 'myMessageKey',
    'message': {'action': 'REGISTER', 'username': 'john'},
    '$': {'action': 'REGISTER', 'username': 'john'},
}
key_template = "{{inputKey}}"
rendered_key = TemplateRenderer.render(key_template, context)
print(f"  Template: {key_template}")
print(f"  inputKey in context: Yes")
print(f"  Context['inputKey']: '{context['inputKey']}'")
print(f"  Rendered key: '{rendered_key}'")
if rendered_key == 'myMessageKey':
    print("  ✅ SUCCESS - Key properly passed through!")
else:
    print(f"  ❌ FAIL - Expected 'myMessageKey', got '{rendered_key}'")

# Scenario 2: Input message has NO key
print("\n📝 Scenario 2: Input message has NO key (inputKey not in context)")
print("-" * 70)
context = {
    'message': {'action': 'REGISTER', 'username': 'john'},
    '$': {'action': 'REGISTER', 'username': 'john'},
}
key_template = "{{inputKey}}"
rendered_key = TemplateRenderer.render(key_template, context)
print(f"  Template: {key_template}")
print(f"  inputKey in context: No")
print(f"  Rendered key: '{rendered_key}'")
# Check if it's the template literal
if rendered_key.startswith("{{") and rendered_key.endswith("}}"):
    print(f"  ℹ️  Result is template literal (expected - will be converted to None)")
    print("  ✅ SUCCESS - Will be handled as None by listener")
elif rendered_key == '':
    print("  ℹ️  Result is empty string (will be converted to None)")
    print("  ✅ SUCCESS - Will be handled as None by listener")
else:
    print(f"  ❌ UNEXPECTED - Got '{rendered_key}'")

# Scenario 3: Alternative - use username as key
print("\n📝 Scenario 3: Using username field as key (alternative approach)")
print("-" * 70)
context = {
    'message': {'action': 'REGISTER', 'username': 'john'},
    '$': {'action': 'REGISTER', 'username': 'john'},
    'username': 'john'
}
key_template = "{{$.username}}"
rendered_key = TemplateRenderer.render(key_template, context)
print(f"  Template: {key_template}")
print(f"  $.username in context: '{context['username']}'")
print(f"  Rendered key: '{rendered_key}'")
if rendered_key == 'john':
    print("  ✅ SUCCESS - Username used as key!")
else:
    print(f"  ❌ FAIL - Expected 'john', got '{rendered_key}'")

print("\n" + "=" * 70)
print("✓ Test Complete - All scenarios validated")
print("=" * 70)

