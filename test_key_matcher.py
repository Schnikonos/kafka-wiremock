#!/usr/bin/env python
"""Test KeyMatcher functionality."""

from src.rules.matcher import KeyMatcher
from src.config.models import Condition

print("=" * 70)
print("Testing KeyMatcher Functionality")
print("=" * 70)

matcher = KeyMatcher()

# Test 1: Match key by value
print("\n✓ Test 1: Match key by exact value")
condition = Condition(type='key', value='myMessageKey')
result = matcher.match('myMessageKey', condition)
print(f"  Key: 'myMessageKey'")
print(f"  Condition: value = 'myMessageKey'")
print(f"  Result: {result.matched}")
assert result.matched, "Should match exact value"
print("  ✓ PASSED")

# Test 2: Key not found (different value)
print("\n✓ Test 2: Key doesn't match")
condition = Condition(type='key', value='differentKey')
result = matcher.match('myMessageKey', condition)
print(f"  Key: 'myMessageKey'")
print(f"  Condition: value = 'differentKey'")
print(f"  Result: {result.matched}")
assert not result.matched, "Should not match different value"
print("  ✓ PASSED")

# Test 3: Match key by regex
print("\n✓ Test 3: Match key by regex")
condition = Condition(type='key', regex='^[a-zA-Z]+Key$')
result = matcher.match('myMessageKey', condition)
print(f"  Key: 'myMessageKey'")
print(f"  Condition: regex = '^[a-zA-Z]+Key$'")
print(f"  Result: {result.matched}")
assert result.matched, "Should match regex pattern"
print("  ✓ PASSED")

# Test 4: Key is None
print("\n✓ Test 4: Key is None")
condition = Condition(type='key', value='someKey')
result = matcher.match(None, condition)
print(f"  Key: None")
print(f"  Condition: value = 'someKey'")
print(f"  Result: {result.matched}")
assert not result.matched, "Should not match when key is None"
print("  ✓ PASSED")

# Test 5: Match key without value/regex (just check existence)
print("\n✓ Test 5: Key exists (no value/regex specified)")
condition = Condition(type='key')
result = matcher.match('ORDER-123', condition)
print(f"  Key: 'ORDER-123'")
print(f"  Condition: just type='key'")
print(f"  Result: {result.matched}")
assert result.matched, "Should match if key exists"
print("  ✓ PASSED")

# Test 6: Order key pattern
print("\n✓ Test 6: Order key pattern matching")
condition = Condition(type='key', regex='^ORDER-[0-9]+$')
result = matcher.match('ORDER-456', condition)
print(f"  Key: 'ORDER-456'")
print(f"  Condition: regex = '^ORDER-[0-9]+$'")
print(f"  Result: {result.matched}")
assert result.matched, "Should match ORDER pattern"
print("  ✓ PASSED")

print("\n" + "=" * 70)
print("✓ All tests PASSED - KeyMatcher is working correctly!")
print("=" * 70)



