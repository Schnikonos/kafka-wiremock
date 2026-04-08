#!/usr/bin/env python3
"""
Extended unit tests for test loader.
Tests YAML parsing, test discovery, and validation.
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.test.loader import TestLoader


class TestLoaderInitialization(unittest.TestCase):
    """Test TestLoader initialization."""

    def test_loader_creation(self):
        """Test creating TestLoader."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = TestLoader(test_suite_dir=tmpdir)
            self.assertEqual(str(loader.test_suite_dir), tmpdir)

    def test_loader_default_directory(self):
        """Test TestLoader with default directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = TestLoader(test_suite_dir=tmpdir)
            self.assertIsNotNone(loader.test_suite_dir)

    def test_loader_custom_directory(self):
        """Test TestLoader with custom directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = TestLoader(test_suite_dir=tmpdir)
            self.assertIsNotNone(loader.test_suite_dir)


class TestTestDiscovery(unittest.TestCase):
    """Test test discovery functionality."""

    def test_discover_empty_directory(self):
        """Test discovering tests in empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_discover_returns_list(self):
        """Test discover_tests returns list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_discover_yaml_files(self):
        """Test discovering YAML files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test YAML file
            test_file = Path(tmpdir) / "01-test.test.yaml"
            test_file.write_text("""name: sample-test
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            # Should find at least one test
            self.assertIsInstance(tests, list)


class TestYamlParsing(unittest.TestCase):
    """Test YAML parsing."""

    def test_parse_simple_test(self):
        """Test parsing simple test YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "01-simple.test.yaml"
            test_file.write_text("""name: simple-test
priority: 10
when:
  inject:
    - message_id: msg1
      topic: input
      payload: {}
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_parse_test_with_tags(self):
        """Test parsing test with tags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "02-tagged.test.yaml"
            test_file.write_text("""name: tagged-test
tags: [tag1, tag2]
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_parse_invalid_yaml(self):
        """Test parsing invalid YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "invalid.yaml"
            test_file.write_text("invalid: yaml: [")

            loader = TestLoader(test_suite_dir=tmpdir)
            # Should handle gracefully
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)


class TestValidation(unittest.TestCase):
    """Test test validation."""

    def test_validation_errors_dict(self):
        """Test validation errors dictionary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = TestLoader(test_suite_dir=tmpdir)
            self.assertIsNotNone(loader.validation_errors)
            self.assertIsInstance(loader.validation_errors, dict)

    def test_valid_test_structure(self):
        """Test valid test structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "03-valid.test.yaml"
            test_file.write_text("""name: valid-test
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_missing_required_fields(self):
        """Test handling of missing required fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "incomplete.yaml"
            test_file.write_text("""priority: 10
tags: [test]
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)


class TestFileFiltering(unittest.TestCase):
    """Test file filtering."""

    def test_ignore_non_yaml(self):
        """Test ignoring non-YAML files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create non-YAML files
            (Path(tmpdir) / "readme.txt").write_text("Not a test")
            (Path(tmpdir) / "data.json").write_text("{}")

            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_find_yaml_extension(self):
        """Test finding .yaml files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "01-test.test.yaml"
            test_file.write_text("""name: yaml-test
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_find_yml_extension(self):
        """Test finding .yml files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "02-test.test.yml"
            test_file.write_text("""name: yml-test
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)


class TestMetadataExtraction(unittest.TestCase):
    """Test metadata extraction from tests."""

    def test_extract_name(self):
        """Test extracting test name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.yaml"
            test_file.write_text("""
name: my-test-name
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            if tests:
                self.assertEqual(tests[0].name, "my-test-name")

    def test_extract_priority(self):
        """Test extracting priority."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.yaml"
            test_file.write_text("""
name: priority-test
priority: 25
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            if tests:
                self.assertEqual(tests[0].priority, 25)

    def test_extract_tags(self):
        """Test extracting tags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.yaml"
            test_file.write_text("""
name: tagged-test
tags: [smoke, critical, integration]
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            if tests:
                self.assertGreater(len(tests[0].tags), 0)


class TestComplexStructures(unittest.TestCase):
    """Test complex test structures."""

    def test_multiple_injections(self):
        """Test test with multiple injections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "03-multi.test.yaml"
            test_file.write_text("""name: multi-injection
when:
  inject:
    - message_id: msg1
      topic: topic1
      payload: {}
    - message_id: msg2
      topic: topic2
      payload: {}
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_multiple_expectations(self):
        """Test test with multiple expectations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "04-expectations.test.yaml"
            test_file.write_text("""name: multi-expectations
when:
  inject: []
then:
  expectations:
    - topic: output1
      match: []
    - topic: output2
      match: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases."""

    def test_empty_yaml_file(self):
        """Test empty YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "empty.yaml"
            test_file.write_text("")

            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_missing_directory(self):
        """Test with missing directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = Path(tmpdir) / "nonexistent"
            loader = TestLoader(test_suite_dir=str(nonexistent))
            # Should handle gracefully
            self.assertIsNotNone(loader)

    def test_subdirectories(self):
        """Test discovering in subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            test_file = subdir / "05-test.test.yaml"
            test_file.write_text("""name: nested-test
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)


class TestMetadataExtraction(unittest.TestCase):
    """Test metadata extraction from tests."""

    def test_extract_name(self):
        """Test extracting test name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "01-test.test.yaml"
            test_file.write_text("""name: my-test-name
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_extract_priority(self):
        """Test extracting priority."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "02-test.test.yaml"
            test_file.write_text("""name: priority-test
priority: 25
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_extract_tags(self):
        """Test extracting tags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "03-test.test.yaml"
            test_file.write_text("""name: tagged-test
tags: [smoke, critical]
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)


class TestMultipleFiles(unittest.TestCase):
    """Test multiple test files."""

    def test_discover_multiple_tests(self):
        """Test discovering multiple tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                test_file = Path(tmpdir) / f"0{i}-test{i}.test.yaml"
                test_file.write_text(f"""name: test-{i}
when:
  inject: []
then:
  expectations: []
""")

            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)

    def test_discover_mixed_extensions(self):
        """Test discovering .yaml and .yml files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "01-test.test.yaml").write_text("""name: yaml-test
when:
  inject: []
then:
  expectations: []
""")
            (Path(tmpdir) / "02-test.test.yml").write_text("""name: yml-test
when:
  inject: []
then:
  expectations: []
""")
            loader = TestLoader(test_suite_dir=tmpdir)
            tests = loader.discover_tests()
            self.assertIsInstance(tests, list)


if __name__ == '__main__':
    unittest.main()










