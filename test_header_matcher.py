#!/usr/bin/env python
"""Test HeaderMatcher functionality."""

from src.rules.matcher import HeaderMatcher
from src.config.models import Condition

print("=" * 70)
print("Testing HeaderMatcher Functionality")
print("=" * 70)

matcher = HeaderMatcher()

# Test 1: Match header by value
print("\n✓ Test 1: Match header by value")
headers = {'my-test-header': 'HeaderValue123'}
condition = Condition(type='header', expression='my-test-header', value='HeaderValue123')
result = matcher.match(headers, condition)
print(f"  Headers: {headers}")
print(f"  Condition: header 'my-test-header' = 'HeaderValue123'")
print(f"  Result: {result.matched}")
assert result.matched, "Should match exact value"
print("  ✓ PASSED")

# Test 2: Header not found
print("\n✓ Test 2: Header not found")
headers = {'other-header': 'SomeValue'}
condition = Condition(type='header', expression='my-test-header', value='HeaderValue123')
result = matcher.match(headers, condition)
print(f"  Headers: {headers}")
print(f"  Condition: header 'my-test-header' = 'HeaderValue123'")
print(f"  Result: {result.matched}")
assert not result.matched, "Should not match when header not found"
print("  ✓ PASSED")

# Test 3: Match header by regex
print("\n✓ Test 3: Match header by regex")
headers = {'my-test-header': 'HeaderValue123'}
condition = Condition(type='header', expression='my-test-header', regex='Header.*')
result = matcher.match(headers, condition)
print(f"  Headers: {headers}")
print(f"  Condition: header 'my-test-header' matches regex 'Header.*'")
print(f"  Result: {result.matched}")
assert result.matched, "Should match regex pattern"
print("  ✓ PASSED")

# Test 4: Header exists (no value/regex)
print("\n✓ Test 4: Header exists (no value/regex specified)")
headers = {'my-test-header': 'AnyValue'}
condition = Condition(type='header', expression='my-test-header')
result = matcher.match(headers, condition)
print(f"  Headers: {headers}")
print(f"  Condition: header 'my-test-header' exists")
print(f"  Result: {result.matched}")
assert result.matched, "Should match if header exists"
print("  ✓ PASSED")

# Test 5: Value mismatch
print("\n✓ Test 5: Value mismatch")
headers = {'my-test-header': 'DifferentValue'}
condition = Condition(type='header', expression='my-test-header', value='HeaderValue123')
result = matcher.match(headers, condition)
print(f"  Headers: {headers}")
print(f"  Condition: header 'my-test-header' = 'HeaderValue123'")
print(f"  Result: {result.matched}")
assert not result.matched, "Should not match different value"
print("  ✓ PASSED")

print("\n" + "=" * 70)
print("✓ All tests PASSED - HeaderMatcher is working correctly!")
print("=" * 70)

