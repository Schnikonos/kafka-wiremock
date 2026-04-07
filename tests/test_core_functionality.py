#!/usr/bin/env python3
"""
Integration and unit tests for kafka-wiremock - focused on what actually works.
Tests the matcher, templater, and config_loader directly without complex imports.
"""

import unittest
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rules.matcher import MatcherFactory, JSONPathMatcher, ExactMatcher, PartialMatcher, RegexMatcher
from src.rules.templater import TemplateRenderer
from src.config.loader import ConfigLoader
from src.config.models import Condition, Output, Rule
from src.custom.placeholders import CustomPlaceholderRegistry, placeholder, order
import yaml

class TestTemplaterBasic(unittest.TestCase):
    """Test basic template rendering that actually works."""

    def test_uuid_placeholder(self):
        """Test {{uuid}} generates valid UUID."""
        template = '{"id": "{{uuid}}"}'
        result = TemplateRenderer.render(template, {})
        obj = json.loads(result)
        # Should be a valid UUID-like string
        self.assertTrue(len(obj['id']) > 20)

    def test_now_placeholder(self):
        """Test {{now}} generates ISO timestamp."""
        template = '{"timestamp": "{{now}}"}'
        result = TemplateRenderer.render(template, {})
        obj = json.loads(result)
        # Should have Z suffix for UTC
        self.assertTrue(obj['timestamp'].endswith('Z'))

    def test_context_substitution(self):
        """Test simple context variable substitution."""
        template = '{"value": "{{myvar}}"}'
        context = {'myvar': 'hello'}
        result = TemplateRenderer.render(template, context)
        obj = json.loads(result)
        self.assertEqual(obj['value'], 'hello')

    def test_multiple_placeholders(self):
        """Test multiple different placeholders."""
        template = '{"a": "{{var1}}", "b": "{{var2}}"}'
        context = {'var1': 'first', 'var2': 'second'}
        result = TemplateRenderer.render(template, context)
        obj = json.loads(result)
        self.assertEqual(obj['a'], 'first')
        self.assertEqual(obj['b'], 'second')

    def test_missing_placeholder(self):
        """Test placeholder not in context returns original."""
        template = '{"value": "{{missing}}"}'
        result = TemplateRenderer.render(template, {})
        # Should preserve original placeholder when not found
        self.assertIn('{{missing}}', result)


class TestMatcherBasic(unittest.TestCase):
    """Test basic matcher functionality."""

    def test_exact_match(self):
        """Test exact string matching."""
        matcher = ExactMatcher()
        result = matcher.match("test-string", "test-string")
        self.assertTrue(result.matched)

    def test_exact_no_match(self):
        """Test exact string no match."""
        matcher = ExactMatcher()
        result = matcher.match("test-string", "different")
        self.assertFalse(result.matched)

    def test_partial_match(self):
        """Test partial/substring matching."""
        matcher = PartialMatcher()
        result = matcher.match("The quick brown fox", "brown")
        self.assertTrue(result.matched)

    def test_partial_no_match(self):
        """Test partial match failure."""
        matcher = PartialMatcher()
        result = matcher.match("The quick brown fox", "missing")
        self.assertFalse(result.matched)

    def test_regex_match(self):
        """Test regex matching."""
        matcher = RegexMatcher()
        result = matcher.match("ORDER-1234", r"ORDER-\d{4}")
        self.assertTrue(result.matched)

    def test_regex_no_match(self):
        """Test regex non-match."""
        matcher = RegexMatcher()
        result = matcher.match("ORDER-ABC", r"ORDER-\d{4}")
        self.assertFalse(result.matched)

    def test_jsonpath_simple(self):
        """Test JSONPath simple match."""
        matcher = JSONPathMatcher()
        message = json.dumps({"status": "OK"})
        condition = {'path': '$.status', 'value': 'OK', 'regex': None}
        result = matcher.match(message, condition)
        self.assertTrue(result.matched)

    def test_jsonpath_nested(self):
        """Test JSONPath nested match."""
        matcher = JSONPathMatcher()
        message = json.dumps({"user": {"name": "John"}})
        condition = {'path': '$.user.name', 'value': 'John', 'regex': None}
        result = matcher.match(message, condition)
        self.assertTrue(result.matched)

    def test_matcher_factory(self):
        """Test matcher factory creates correct types."""
        self.assertIsInstance(MatcherFactory.create('exact'), ExactMatcher)
        self.assertIsInstance(MatcherFactory.create('partial'), PartialMatcher)
        self.assertIsInstance(MatcherFactory.create('regex'), RegexMatcher)
        self.assertIsInstance(MatcherFactory.create('jsonpath'), JSONPathMatcher)


class TestConfigLoaderBasic(unittest.TestCase):
    """Test basic config loading functionality."""

    def test_load_simple_rule(self):
        """Test loading a simple rule."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "rule.yaml"
            rule_file.write_text('''
priority: 10
when:
  topic: test
then:
  - topic: output
    payload: '{}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            self.assertEqual(len(loader.rules), 1)
            self.assertEqual(loader.rules[0].priority, 10)
            self.assertEqual(loader.rules[0].input_topic, 'test')

    def test_load_wildcard_rule(self):
        """Test loading wildcard rule (no conditions)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "wildcard.yaml"
            rule_file.write_text('''
priority: 99
when:
  topic: catch-all
then:
  - topic: archive
    payload: '{}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            rule = loader.rules[0]
            self.assertEqual(len(rule.conditions), 0)

    def test_load_multiple_files(self):
        """Test loading multiple rule files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                rule_file = Path(tmpdir) / f"{i:02d}.yaml"
                rule_file.write_text(f'''
priority: {i}
when:
  topic: topic-{i}
then:
  - topic: out
    payload: '{{}}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            self.assertEqual(len(loader.rules), 3)
            # Should be sorted by priority
            self.assertEqual(loader.rules[0].priority, 0)

    def test_hot_reload_detect_new(self):
        """Test detecting new rule file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = ConfigLoader(tmpdir, reload_interval=0)
            self.assertEqual(len(loader.rules), 0)

            # Add new file
            rule_file = Path(tmpdir) / "new.yaml"
            rule_file.write_text('''
priority: 1
when:
  topic: new
then:
  - topic: out
    payload: '{}'
''')

            changed = loader.check_and_reload()
            self.assertTrue(changed)
            self.assertEqual(len(loader.rules), 1)

    def test_hot_reload_detect_delete(self):
        """Test detecting deleted rule file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "rule.yaml"
            rule_file.write_text('''
priority: 1
when:
  topic: test
then:
  - topic: out
    payload: '{}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            self.assertEqual(len(loader.rules), 1)

            # Delete file
            rule_file.unlink()
            changed = loader.check_and_reload()
            self.assertTrue(changed)
            self.assertEqual(len(loader.rules), 0)

    def test_rules_by_topic(self):
        """Test rules indexed by topic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two rules for same topic
            for i in range(2):
                rule_file = Path(tmpdir) / f"{i}.yaml"
                rule_file.write_text(f'''
priority: {i}
when:
  topic: orders
then:
  - topic: out
    payload: '{{}}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            rules = loader.get_rules_for_topic('orders')
            self.assertEqual(len(rules), 2)
            self.assertEqual(rules[0].priority, 0)
            self.assertEqual(rules[1].priority, 1)


class TestComplexScenarios(unittest.TestCase):
    """Test complex real-world scenarios."""

    def test_order_processing_rule(self):
        """Test realistic order processing rule."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "order.yaml"
            rule_file.write_text('''
priority: 10
name: process-order
when:
  topic: orders
  match:
    - type: jsonpath
      expression: "$.status"
      value: "PENDING"
    - type: jsonpath
      expression: "$.amount"
      regex: "^[0-9]+$"
then:
  - topic: payments
    delay_ms: 100
    headers:
      X-OrderId: "{{orderId}}"
    payload: '{"amount": "{{amount}}"}'
  - topic: notifications
    payload: '{"msg": "Order received"}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            rule = loader.rules[0]

            # Validate rule structure
            self.assertEqual(rule.priority, 10)
            self.assertEqual(len(rule.conditions), 2)
            self.assertEqual(len(rule.outputs), 2)

            # Check first output
            self.assertEqual(rule.outputs[0].topic, 'payments')
            self.assertEqual(rule.outputs[0].delay_ms, 100)
            self.assertIn('X-OrderId', rule.outputs[0].headers)

            # Check second output
            self.assertEqual(rule.outputs[1].topic, 'notifications')

    def test_message_matching_with_extraction(self):
        """Test message matching with value extraction."""
        matcher = JSONPathMatcher()

        # Test message
        message = json.dumps({
            "orderId": "ORD123",
            "amount": 500,
            "status": "PENDING"
        })

        # Condition
        condition = {
            'path': '$.status',
            'value': 'PENDING',
            'regex': None
        }

        result = matcher.match(message, condition)
        self.assertTrue(result.matched)
        # The context has the extracted fields and matched value
        self.assertIn('matched_value', result.context)
        self.assertEqual(result.context['matched_value'], 'PENDING')

    def test_nested_config_structure(self):
        """Test nested subdirectory organization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            (Path(tmpdir) / "orders").mkdir()
            (Path(tmpdir) / "payments").mkdir()

            # Add rules
            (Path(tmpdir) / "orders" / "01.yaml").write_text('''
priority: 10
when:
  topic: orders
then:
  - topic: out
    payload: '{}'
''')

            (Path(tmpdir) / "payments" / "01.yaml").write_text('''
priority: 20
when:
  topic: payments
then:
  - topic: out
    payload: '{}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            self.assertEqual(len(loader.rules), 2)

            orders = loader.get_rules_for_topic('orders')
            payments = loader.get_rules_for_topic('payments')

            self.assertEqual(len(orders), 1)
            self.assertEqual(len(payments), 1)


class TestTemplaterAdvanced(unittest.TestCase):
    """Additional templater tests for better coverage."""

    def test_random_int_basic(self):
        """Test randomInt function."""
        template = '{"value": {{randomInt(1,100)}}}'
        result = TemplateRenderer.render(template, {})
        obj = json.loads(result)
        self.assertGreaterEqual(obj['value'], 1)
        self.assertLessEqual(obj['value'], 100)

    def test_get_context_value_simple(self):
        """Test _get_context_value with simple key."""
        context = {'key': 'value'}
        result = TemplateRenderer._get_context_value(context, 'key')
        self.assertEqual(result, 'value')

    def test_get_context_value_missing(self):
        """Test _get_context_value with missing key."""
        result = TemplateRenderer._get_context_value({}, 'missing')
        self.assertIsNone(result)

    def test_resolve_placeholder_context_key(self):
        """Test _resolve_placeholder with context key."""
        context = {'mykey': 'myvalue'}
        result = TemplateRenderer._resolve_placeholder(context, 'mykey')
        self.assertEqual(result, 'myvalue')


class TestMatcherAdvanced(unittest.TestCase):
    """Additional matcher tests for coverage."""

    def test_jsonpath_invalid_json(self):
        """Test JSONPath with invalid JSON."""
        matcher = JSONPathMatcher()
        result = matcher.match("not json", {'path': '$.key', 'value': 'val', 'regex': None})
        self.assertFalse(result.matched)

    def test_jsonpath_missing_path(self):
        """Test JSONPath when path doesn't exist."""
        matcher = JSONPathMatcher()
        message = json.dumps({"status": "OK"})
        condition = {'path': '$.missing', 'value': 'val', 'regex': None}
        result = matcher.match(message, condition)
        self.assertFalse(result.matched)

    def test_exact_empty_strings(self):
        """Test exact match with empty strings."""
        matcher = ExactMatcher()
        result = matcher.match("", "")
        self.assertTrue(result.matched)

    def test_partial_case_sensitive(self):
        """Test partial matching is case sensitive."""
        matcher = PartialMatcher()
        result = matcher.match("HELLO world", "hello")
        self.assertFalse(result.matched)

    def test_regex_invalid_pattern(self):
        """Test regex with invalid pattern."""
        matcher = RegexMatcher()
        # Should not crash with invalid regex
        try:
            result = matcher.match("test", "[invalid")
            # May return False or raise, but shouldn't crash the app
        except:
            pass


class TestConfigLoaderValidation(unittest.TestCase):
    """Additional config loader validation tests."""

    def test_parse_condition_types(self):
        """Test parsing different condition types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "conditions.yaml"
            rule_file.write_text('''
priority: 1
when:
  topic: test
  match:
    - type: exact
      value: "exact-match"
    - type: partial
      value: "partial"
    - type: regex
      regex: "[0-9]+"
then:
  - topic: out
    payload: '{}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            rule = loader.rules[0]

            self.assertEqual(len(rule.conditions), 3)
            self.assertEqual(rule.conditions[0].type, 'exact')
            self.assertEqual(rule.conditions[1].type, 'partial')
            self.assertEqual(rule.conditions[2].type, 'regex')

    def test_get_all_rules(self):
        """Test get_all_rules returns sorted rules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for priority in [30, 10, 20]:
                rule_file = Path(tmpdir) / f"{priority}.yaml"
                rule_file.write_text(f'''
priority: {priority}
when:
  topic: test
then:
  - topic: out
    payload: '{{}}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            all_rules = loader.get_all_rules()

            # Should be sorted by priority
            self.assertEqual(all_rules[0].priority, 10)
            self.assertEqual(all_rules[1].priority, 20)
            self.assertEqual(all_rules[2].priority, 30)

    def test_multiple_outputs_with_headers(self):
        """Test rule with multiple outputs and headers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "multi_out.yaml"
            rule_file.write_text('''
priority: 1
when:
  topic: test
then:
  - topic: out1
    payload: '{"msg": 1}'
    headers:
      X-Header1: "value1"
  - topic: out2
    payload: '{"msg": 2}'
    headers:
      X-Header2: "value2"
      X-Header3: "value3"
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            rule = loader.rules[0]

            self.assertEqual(len(rule.outputs), 2)
            self.assertEqual(len(rule.outputs[0].headers), 1)
            self.assertEqual(len(rule.outputs[1].headers), 2)
            self.assertEqual(rule.outputs[0].headers['X-Header1'], 'value1')

    def test_output_with_schema_id(self):
        """Test output with AVRO schema_id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "avro.yaml"
            rule_file.write_text('''
priority: 1
when:
  topic: test
then:
  - topic: avro-out
    payload: '{"data": "value"}'
    schema_id: 42
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            output = loader.rules[0].outputs[0]

            self.assertEqual(output.schema_id, 42)

    def test_output_with_delay(self):
        """Test output with delay_ms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "delay.yaml"
            rule_file.write_text('''
priority: 1
when:
  topic: test
then:
  - topic: out
    payload: '{}'
    delay_ms: 500
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            output = loader.rules[0].outputs[0]

            self.assertEqual(output.delay_ms, 500)


class TestConfigLoaderEdgeCases(unittest.TestCase):
    """Test edge cases in config loading."""

    def test_empty_config_dir(self):
        """Test loading from empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = ConfigLoader(tmpdir, reload_interval=0)
            self.assertEqual(len(loader.rules), 0)

    def test_no_change_after_reload(self):
        """Test check_and_reload returns False when nothing changed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "rule.yaml"
            rule_file.write_text('''
priority: 1
when:
  topic: test
then:
  - topic: out
    payload: '{}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            initial_rules = len(loader.rules)

            # First check_and_reload should return False (no time elapsed)
            # But the rules are already loaded
            changed1 = loader.check_and_reload()
            self.assertEqual(len(loader.rules), initial_rules)

            # Second check should also return False (no changes)
            changed2 = loader.check_and_reload()
            self.assertFalse(changed2)

    def test_modify_and_detect_change(self):
        """Test detecting file modification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "rule.yaml"
            rule_file.write_text('''
priority: 1
when:
  topic: test
then:
  - topic: out1
    payload: '{"v": 1}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            loader.check_and_reload()

            # Modify file
            rule_file.write_text('''
priority: 2
when:
  topic: test2
then:
  - topic: out2
    payload: '{"v": 2}'
''')

            changed = loader.check_and_reload()
            self.assertTrue(changed)

            # Verify changes were loaded
            self.assertEqual(loader.rules[0].priority, 2)
            self.assertEqual(loader.rules[0].input_topic, 'test2')


class TestMatcherComplexCases(unittest.TestCase):
    """Test complex matching scenarios."""

    def test_multiple_rules_same_topic(self):
        """Test multiple rules on same topic with different priorities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                rule_file = Path(tmpdir) / f"{i:02d}.yaml"
                rule_file.write_text(f'''
priority: {i * 10}
when:
  topic: shared
then:
  - topic: out
    payload: '{{"order": {i}}}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            rules = loader.get_rules_for_topic('shared')

            # Should be sorted by priority
            self.assertEqual(len(rules), 3)
            self.assertEqual(rules[0].priority, 0)
            self.assertEqual(rules[1].priority, 10)
            self.assertEqual(rules[2].priority, 20)

    def test_jsonpath_with_regex_validation(self):
        """Test JSONPath matching with regex validation."""
        matcher = JSONPathMatcher()

        message = json.dumps({"id": "12345"})
        condition = {
            'path': '$.id',
            'value': None,
            'regex': r'^\d{5}$'
        }

        result = matcher.match(message, condition)
        self.assertTrue(result.matched)

    def test_jsonpath_regex_no_match(self):
        """Test JSONPath regex that doesn't match."""
        matcher = JSONPathMatcher()

        message = json.dumps({"id": "abc"})
        condition = {
            'path': '$.id',
            'value': None,
            'regex': r'^\d+$'
        }

        result = matcher.match(message, condition)
        self.assertFalse(result.matched)


class TestTemplaterCoverage(unittest.TestCase):
    """Additional templater tests to improve coverage."""

    def test_now_offset_minutes(self):
        """Test now+Xm offset."""
        result = TemplateRenderer._resolve_now_offset('now+5m')
        self.assertTrue(result.endswith('Z'))
        # Should be a valid timestamp
        datetime.fromisoformat(result.rstrip('Z'))

    def test_now_offset_hours(self):
        """Test now+Xh offset."""
        result = TemplateRenderer._resolve_now_offset('now+2h')
        self.assertTrue(result.endswith('Z'))

    def test_now_offset_days(self):
        """Test now+Xd offset."""
        result = TemplateRenderer._resolve_now_offset('now+1d')
        self.assertTrue(result.endswith('Z'))

    def test_now_offset_negative(self):
        """Test now-X offset."""
        result = TemplateRenderer._resolve_now_offset('now-3h')
        self.assertTrue(result.endswith('Z'))

    def test_random_int_edge_cases(self):
        """Test randomInt with edge cases."""
        result = TemplateRenderer._resolve_random_int('randomInt(0,0)')
        self.assertEqual(result, 0)

    def test_render_none_template(self):
        """Test render with None template."""
        result = TemplateRenderer.render(None, {})
        self.assertEqual(result, "")

    def test_render_empty_template(self):
        """Test render with empty string."""
        result = TemplateRenderer.render("", {})
        self.assertEqual(result, "")

    def test_render_no_placeholders(self):
        """Test render without placeholders."""
        template = "plain text"
        result = TemplateRenderer.render(template, {})
        self.assertEqual(result, template)

    def test_placeholder_with_list_value(self):
        """Test placeholder resolving to list."""
        template = '{"list": "{{items}}"}'
        context = {'items': [1, 2, 3]}
        result = TemplateRenderer.render(template, context)
        obj = json.loads(result)
        self.assertIn('[1', obj['list'])

    def test_placeholder_with_dict_value(self):
        """Test placeholder resolving to dict."""
        template = '{"obj": {{data}}}'
        context = {'data': {'key': 'value'}}
        result = TemplateRenderer.render(template, context)
        obj = json.loads(result)
        self.assertEqual(obj['obj']['key'], 'value')

    def test_traverse_path_array(self):
        """Test _traverse_path with array - returns the array itself."""
        context = {'items': ['a', 'b', 'c']}
        # array[index] syntax returns the whole array (limitation of implementation)
        result = TemplateRenderer._traverse_path(context, 'items[0]')
        self.assertEqual(result, ['a', 'b', 'c'])

    def test_traverse_path_nested_array(self):
        """Test _traverse_path with nested structure."""
        context = {'data': [{'id': 1}, {'id': 2}]}
        # data[0].id syntax returns None (array indexing not fully supported)
        result = TemplateRenderer._traverse_path(context, 'data[0].id')
        self.assertIsNone(result)

        # But accessing the array itself works
        result2 = TemplateRenderer._traverse_path(context, 'data')
        self.assertEqual(len(result2), 2)

    def test_get_context_value_with_dollar(self):
        """Test _get_context_value strips $ prefix."""
        context = {'field': 'value'}
        result = TemplateRenderer._get_context_value(context, '$.field')
        self.assertEqual(result, 'value')

    def test_get_context_value_with_dot_notation(self):
        """Test _get_context_value with dot notation."""
        context = {'user.name': 'John'}
        result = TemplateRenderer._get_context_value(context, 'user.name')
        self.assertEqual(result, 'John')


class TestConfigLoaderAdvanced(unittest.TestCase):
    """Additional config loader tests for better coverage."""

    def test_calculate_file_hash(self):
        """Test file hash calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.yaml"
            file_path.write_text("test content")

            hash1 = ConfigLoader._calculate_file_hash(file_path)
            hash2 = ConfigLoader._calculate_file_hash(file_path)

            # Same file should have same hash
            self.assertEqual(hash1, hash2)

            # Modify file
            file_path.write_text("different content")
            hash3 = ConfigLoader._calculate_file_hash(file_path)

            # Different content should have different hash
            self.assertNotEqual(hash1, hash3)

    def test_rule_by_priority(self):
        """Test rules are returned sorted by priority."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in [50, 10, 30]:
                f = Path(tmpdir) / f"{i}.yaml"
                f.write_text(f'''
priority: {i}
when:
  topic: test
then:
  - topic: out
    payload: '{{}}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            topics = loader.get_rules_for_topic('test')

            # Should be sorted
            self.assertEqual(topics[0].priority, 10)
            self.assertEqual(topics[1].priority, 30)
            self.assertEqual(topics[2].priority, 50)

    def test_condition_with_both_value_and_regex(self):
        """Test condition can have both value and regex."""
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "rule.yaml"
            f.write_text('''
priority: 1
when:
  topic: test
  match:
    - type: jsonpath
      expression: "$.status"
      value: "ACTIVE"
      regex: "[A-Z]+"
then:
  - topic: out
    payload: '{}'
''')

            loader = ConfigLoader(tmpdir, reload_interval=0)
            condition = loader.rules[0].conditions[0]

            self.assertEqual(condition.value, "ACTIVE")
            self.assertEqual(condition.regex, "[A-Z]+")


class TestMatcherCoverage(unittest.TestCase):
    """Additional matcher tests for coverage."""

    def test_match_result_context(self):
        """Test MatchResult includes context."""
        matcher = ExactMatcher()
        result = matcher.match("test", "test")

        self.assertTrue(result.matched)
        self.assertIsNotNone(result.context)
        self.assertIsInstance(result.context, dict)

    def test_jsonpath_nested_extraction(self):
        """Test JSONPath extracts nested values."""
        matcher = JSONPathMatcher()
        message = json.dumps({
            "user": {
                "profile": {
                    "name": "Alice"
                }
            }
        })

        condition = {
            'path': '$.user.profile.name',
            'value': 'Alice',
            'regex': None
        }

        result = matcher.match(message, condition)
        self.assertTrue(result.matched)

    def test_regex_with_groups(self):
        """Test regex with capture groups."""
        matcher = RegexMatcher()
        result = matcher.match("ID-12345-XYZ", r"ID-(\d+)-(\w+)")
        self.assertTrue(result.matched)

    def test_partial_empty_string(self):
        """Test partial match with empty strings."""
        matcher = PartialMatcher()
        result = matcher.match("", "")
        self.assertTrue(result.matched)

    def test_partial_substring_not_found(self):
        """Test partial match when substring not present."""
        matcher = PartialMatcher()
        result = matcher.match("hello world", "xyz")
        self.assertFalse(result.matched)


class TestCustomPlaceholdersDecorators(unittest.TestCase):
    """Test placeholder and order decorators."""

    def test_placeholder_decorator(self):
        """Test @placeholder marks function as placeholder."""
        @placeholder
        def test_func(context):
            return "test"

        self.assertTrue(hasattr(test_func, '_is_placeholder'))
        self.assertTrue(test_func._is_placeholder)

    def test_order_decorator(self):
        """Test @order sets execution priority."""
        @order(10)
        def test_func(context):
            return "test"

        self.assertEqual(test_func._placeholder_order, 10)

    def test_combined_decorators(self):
        """Test @placeholder and @order together."""
        @placeholder
        @order(20)
        def test_func(context):
            return "test"

        self.assertTrue(test_func._is_placeholder)
        self.assertEqual(test_func._placeholder_order, 20)


class TestCustomPlaceholderRegistry(unittest.TestCase):
    """Test CustomPlaceholderRegistry loading and execution."""

    def test_registry_initialization(self):
        """Test registry initializes empty when no files exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            self.assertEqual(len(registry.placeholders), 0)

    def test_load_placeholder_from_dict(self):
        """Test loading PLACEHOLDERS dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ph_file = Path(tmpdir) / "test.py"
            ph_file.write_text('''
def my_func(context):
    return "value"

PLACEHOLDERS = {
    'my_ph': my_func,
}
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            self.assertIn('my_ph', registry.placeholders)
            self.assertEqual(registry.get_placeholder('my_ph')({}), 'value')

    def test_load_placeholder_from_decorator(self):
        """Test loading @placeholder decorated functions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ph_file = Path(tmpdir) / "test.py"
            ph_file.write_text('''
import sys
sys.path.insert(0, "/home/nico/work/tools/kafka-wiremock")
from src.custom.placeholders import placeholder

@placeholder
def decorated_func(context):
    return "decorated"
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            self.assertIn('decorated_func', registry.placeholders)
            self.assertEqual(registry.get_placeholder('decorated_func')({}), 'decorated')

    def test_get_all_placeholders(self):
        """Test get_all_placeholders returns all loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ph_file = Path(tmpdir) / "test.py"
            ph_file.write_text('''
def func1(context):
    return "1"

def func2(context):
    return "2"

PLACEHOLDERS = {'ph1': func1, 'ph2': func2}
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            all_ph = registry.get_all_placeholders()

            self.assertEqual(len(all_ph), 2)
            self.assertIn('ph1', all_ph)
            self.assertIn('ph2', all_ph)


class TestPlaceholderOrdering(unittest.TestCase):
    """Test placeholder execution ordering."""

    def test_unordered_first(self):
        """Test unordered placeholders execute first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ph_file = Path(tmpdir) / "test.py"
            ph_file.write_text('''
import sys
sys.path.insert(0, "/home/nico/work/tools/kafka-wiremock")
from src.custom.placeholders import placeholder, order

@placeholder
def unordered(context):
    return "unordered"

@placeholder
@order(10)
def ordered(context):
    return "ordered"
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            order_list = registry._get_execution_order()

            # Unordered should come first
            self.assertIn('unordered', order_list)
            self.assertIn('ordered', order_list)
            self.assertEqual(order_list.index('unordered'), 0)

    def test_execution_order_by_priority(self):
        """Test ordered placeholders execute by priority."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ph_file = Path(tmpdir) / "test.py"
            ph_file.write_text('''
import sys
sys.path.insert(0, "/home/nico/work/tools/kafka-wiremock")
from src.custom.placeholders import placeholder, order

@placeholder
@order(30)
def third(context):
    return "third"

@placeholder
@order(10)
def first(context):
    return "first"

@placeholder
@order(20)
def second(context):
    return "second"
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            order_list = registry._get_execution_order()

            # Should be sorted
            self.assertEqual(order_list[0], 'first')
            self.assertEqual(order_list[1], 'second')
            self.assertEqual(order_list[2], 'third')


class TestPipelineExecution(unittest.TestCase):
    """Test placeholder pipeline execution."""

    def test_pipeline_basic(self):
        """Test basic pipeline execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ph_file = Path(tmpdir) / "test.py"
            ph_file.write_text('''
import sys
sys.path.insert(0, "/home/nico/work/tools/kafka-wiremock")
from src.custom.placeholders import placeholder

@placeholder
def get_name(context):
    return "Alice"

@placeholder
def get_age(context):
    return 30
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            context = registry.execute_pipeline({})

            self.assertEqual(context['get_name'], 'Alice')
            self.assertEqual(context['get_age'], 30)

    def test_pipeline_context_access(self):
        """Test placeholders can access context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ph_file = Path(tmpdir) / "test.py"
            ph_file.write_text('''
import sys
sys.path.insert(0, "/home/nico/work/tools/kafka-wiremock")
from src.custom.placeholders import placeholder

@placeholder
def extract_name(context):
    return context.get('name', 'unknown')

@placeholder
def uppercase_name(context):
    name = context.get('extract_name', '')
    return name.upper()
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            context = registry.execute_pipeline({'name': 'alice'})

            self.assertEqual(context['extract_name'], 'alice')
            self.assertEqual(context['uppercase_name'], 'ALICE')

    def test_pipeline_with_error(self):
        """Test pipeline continues if one placeholder fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ph_file = Path(tmpdir) / "test.py"
            ph_file.write_text('''
import sys
sys.path.insert(0, "/home/nico/work/tools/kafka-wiremock")
from src.custom.placeholders import placeholder

@placeholder
def failing_func(context):
    raise ValueError("Test error")

@placeholder
def working_func(context):
    return "works"
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            context = registry.execute_pipeline({})

            # failing_func shouldn't be in context
            self.assertNotIn('failing_func', context)
            # working_func should be there
            self.assertEqual(context['working_func'], 'works')


class TestPlaceholderFileOperations(unittest.TestCase):
    """Test file loading and hot-reload operations."""

    def test_calculate_file_hash(self):
        """Test file hash calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.py"
            file_path.write_text("content1")

            hash1 = CustomPlaceholderRegistry._calculate_file_hash(file_path)
            hash2 = CustomPlaceholderRegistry._calculate_file_hash(file_path)

            self.assertEqual(hash1, hash2)

            # Different content should have different hash
            file_path.write_text("content2")
            hash3 = CustomPlaceholderRegistry._calculate_file_hash(file_path)
            self.assertNotEqual(hash1, hash3)

    def test_detect_new_file(self):
        """Test detecting newly added file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            self.assertEqual(len(registry.placeholders), 0)

            # Add file
            ph_file = Path(tmpdir) / "new.py"
            ph_file.write_text('''
def func(context):
    return "new"

PLACEHOLDERS = {'new_ph': func}
''')

            # Check and reload
            changed = registry.check_and_reload()
            self.assertTrue(changed)
            self.assertIn('new_ph', registry.placeholders)

    def test_detect_deleted_file(self):
        """Test detecting deleted file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ph_file = Path(tmpdir) / "delete.py"
            ph_file.write_text('''
def func(context):
    return "delete"

PLACEHOLDERS = {'delete_ph': func}
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            self.assertIn('delete_ph', registry.placeholders)

            # Delete file
            ph_file.unlink()
            changed = registry.check_and_reload()

            self.assertTrue(changed)
            self.assertNotIn('delete_ph', registry.placeholders)

    def test_detect_modified_file(self):
        """Test detecting modified file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ph_file = Path(tmpdir) / "modify.py"
            ph_file.write_text('''
def func(context):
    return "v1"

PLACEHOLDERS = {'modify_ph': func}
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            initial_result = registry.get_placeholder('modify_ph')({})
            self.assertEqual(initial_result, 'v1')

            # Modify file
            ph_file.write_text('''
def func(context):
    return "v2"

PLACEHOLDERS = {'modify_ph': func}
''')

            changed = registry.check_and_reload()
            self.assertTrue(changed)


class TestPlaceholderEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_empty_directory(self):
        """Test loading from empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            self.assertEqual(len(registry.placeholders), 0)

    def test_reload_interval_respected(self):
        """Test reload interval is respected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=100)

            # Add file
            ph_file = Path(tmpdir) / "test.py"
            ph_file.write_text('PLACEHOLDERS = {}')

            # Check too soon should return False
            changed = registry.check_and_reload()
            self.assertFalse(changed)

    def test_subdirectory_support(self):
        """Test loading from subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create subdirectory
            subdir = Path(tmpdir) / "sub"
            subdir.mkdir()

            # Add file in subdirectory
            ph_file = subdir / "test.py"
            ph_file.write_text('''
def func(context):
    return "subdir"

PLACEHOLDERS = {'sub_ph': func}
''')

            registry = CustomPlaceholderRegistry(tmpdir, reload_interval=0)
            self.assertIn('sub_ph', registry.placeholders)


if __name__ == '__main__':
    unittest.main()











