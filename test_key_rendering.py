#!/usr/bin/env python
"""Test script to verify inputKey template rendering."""

from src.rules.templater import TemplateRenderer

print("=" * 60)
print("Testing inputKey Template Rendering")
print("=" * 60)

# Test 1: Key exists in context
print("\nTest 1: Key exists in context")
context = {'inputKey': 'myMessageKey', 'message': {}}
result = TemplateRenderer.render("{{inputKey}}", context)
print(f"  Template: '{{{{inputKey}}}}'")
print(f"  Context inputKey: '{context['inputKey']}'")
print(f"  Rendered result: '{result}'")
print(f"  ✓ SUCCESS" if result == 'myMessageKey' else f"  ✗ FAIL")

# Test 2: Key doesn't exist in context
print("\nTest 2: Key doesn't exist in context")
context = {'message': {}}
result = TemplateRenderer.render("{{inputKey}}", context)
print(f"  Template: '{{{{inputKey}}}}'")
print(f"  Context keys: {list(context.keys())}")
print(f"  Rendered result: '{result}'")
print(f"  ✓ Expected (template returned as-is)" if result.startswith("{{") else f"  ? Unexpected")

# Test 3: Null value in context
print("\nTest 3: Null value in context")
context = {'inputKey': None, 'message': {}}
result = TemplateRenderer.render("{{inputKey}}", context)
print(f"  Template: '{{{{inputKey}}}}'")
print(f"  Context inputKey: {context['inputKey']}")
print(f"  Rendered result: '{result}'")
print(f"  Type: {type(result)}")

print("\n" + "=" * 60)
print("Test Complete")
print("=" * 60)

