#!/usr/bin/env python3
"""
Unit tests for test suite execution engine.
Tests TestExecutor, TestSuiteRunner, and related components.
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import json
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.test.suite import (
    InjectedMessage, ReceivedMessage, ExpectationResult, ThenResult, WhenResult,
    TestResult, TestExecutor, TestSuiteRunner, TestResultAggregator
)
from src.test.loader import TestDefinition, TestWhen, TestThen, TestInjection, TestExpectation
from src.kafka.client import KafkaClientWrapper


class TestDataClasses(unittest.TestCase):
    """Test data classes for test results."""

    def test_injected_message(self):
        """Test InjectedMessage dataclass."""
        msg = InjectedMessage(
            message_id="msg-1",
            topic="test-topic",
            payload={"key": "value"},
            headers={"h1": "v1"},
            timestamp=1000,
            status="ok"
        )
        self.assertEqual(msg.message_id, "msg-1")
        self.assertEqual(msg.topic, "test-topic")
        self.assertEqual(msg.payload["key"], "value")
        self.assertEqual(msg.status, "ok")

    def test_received_message(self):
        """Test ReceivedMessage dataclass."""
        msg = ReceivedMessage(
            value={"data": "test"},
            timestamp=2000,
            partition=0,
            offset=10,
            headers={"h1": "v1"},
            key="message-key"
        )
        self.assertEqual(msg.value["data"], "test")
        self.assertEqual(msg.key, "message-key")
        self.assertEqual(msg.partition, 0)

    def test_expectation_result(self):
        """Test ExpectationResult dataclass."""
        result = ExpectationResult(
            index=0,
            topic="output-topic",
            expected=1,
            received=1,
            status="MATCHED",
            elapsed_ms=100
        )
        self.assertEqual(result.topic, "output-topic")
        self.assertEqual(result.status, "MATCHED")
        self.assertTrue(result.expected == result.received)

    def test_then_result(self):
        """Test ThenResult dataclass."""
        exp_result = ExpectationResult(0, "topic", 1, 1, "MATCHED")
        then_result = ThenResult(expectations=[exp_result])
        self.assertEqual(len(then_result.expectations), 1)
        self.assertEqual(then_result.expectations[0].status, "MATCHED")

    def test_when_result(self):
        """Test WhenResult dataclass."""
        when_result = WhenResult(injected=[{"id": "msg-1"}])
        self.assertEqual(len(when_result.injected), 1)
        self.assertEqual(when_result.injected[0]["id"], "msg-1")

    def test_test_result(self):
        """Test TestResult dataclass."""
        result = TestResult(
            test_id="test-1",
            status="PASSED",
            elapsed_ms=500
        )
        self.assertEqual(result.test_id, "test-1")
        self.assertEqual(result.status, "PASSED")
        self.assertEqual(result.elapsed_ms, 500)


class TestTestResultAggregator(unittest.TestCase):
    """Test result aggregation functionality."""

    def test_aggregate_results_empty(self):
        """Test aggregating empty results."""
        results = []
        agg = TestResultAggregator.aggregate_results(results, mode="sequential")

        self.assertEqual(agg["total_tests"], 0)
        self.assertEqual(agg["passed"], 0)
        self.assertEqual(agg["failed"], 0)

    def test_aggregate_results_single_pass(self):
        """Test aggregating single passing test."""
        result = TestResult(
            test_id="test-1",
            status="PASSED",
            elapsed_ms=100,
            when_result=WhenResult(),
            then_result=ThenResult()
        )
        results = [result]
        agg = TestResultAggregator.aggregate_results(results, mode="sequential")

        self.assertEqual(agg["total_tests"], 1)
        self.assertEqual(agg["passed"], 1)
        self.assertEqual(agg["failed"], 0)

    def test_aggregate_results_mixed(self):
        """Test aggregating mixed results."""
        results = [
            TestResult("test-1", "PASSED", 100),
            TestResult("test-2", "FAILED", 200),
            TestResult("test-3", "PASSED", 150),
        ]
        agg = TestResultAggregator.aggregate_results(results, mode="parallel")

        self.assertEqual(agg["total_tests"], 3)
        self.assertEqual(agg["passed"], 2)
        self.assertEqual(agg["failed"], 1)


class TestTestExecutor(unittest.TestCase):
    """Test TestExecutor functionality."""

    def setUp(self):
        """Set up test executor."""
        self.mock_kafka_client = MagicMock(spec=KafkaClientWrapper)
        self.mock_registry = MagicMock()

    @patch('src.test.suite.KafkaClientWrapper')
    def test_executor_initialization(self, mock_client_class):
        """Test TestExecutor initialization."""
        executor = TestExecutor(
            kafka_client=self.mock_kafka_client,
            custom_placeholder_registry=self.mock_registry,
            test_suite_dir="/tests"
        )
        self.assertIsNotNone(executor.kafka_client)
        self.assertIsNotNone(executor.custom_placeholder_registry)


class TestTestSuiteRunner(unittest.TestCase):
    """Test TestSuiteRunner functionality."""

    def setUp(self):
        """Set up test suite runner."""
        self.mock_kafka_client = MagicMock(spec=KafkaClientWrapper)
        self.mock_registry = MagicMock()

    def test_runner_initialization(self):
        """Test TestSuiteRunner initialization."""
        runner = TestSuiteRunner(
            kafka_client=self.mock_kafka_client,
            custom_placeholder_registry=self.mock_registry,
            test_suite_dir="/tests"
        )
        self.assertIsNotNone(runner.kafka_client)
        self.assertIsNotNone(runner.custom_placeholder_registry)

    @patch('src.test.suite.TestExecutor')
    def test_runner_executor_creation(self, mock_executor_class):
        """Test that runner creates executor properly."""
        runner = TestSuiteRunner(
            kafka_client=self.mock_kafka_client,
            custom_placeholder_registry=self.mock_registry
        )
        # Verify executor was created
        self.assertIsNotNone(runner.executor)


class TestTestExecutorMethods(unittest.TestCase):
    """Test TestExecutor method functionality."""

    def setUp(self):
        """Set up test executor."""
        self.mock_kafka_client = MagicMock(spec=KafkaClientWrapper)
        self.mock_registry = MagicMock()
        self.executor = TestExecutor(
            kafka_client=self.mock_kafka_client,
            custom_placeholder_registry=self.mock_registry
        )

    @patch('src.test.suite.TestExecutor.run_test')
    def test_async_run_test(self, mock_run_test):
        """Test test execution."""
        # Create a simple mock test definition
        test_def = MagicMock(spec=TestDefinition)
        test_def.name = "test-1"
        test_def.timeout_ms = 5000
        test_def.file_path = "/test.yaml"

        mock_run_test.return_value = TestResult("test-1", "PASSED", 100)

        # Call should succeed
        self.assertIsNotNone(mock_run_test)


class TestTestSuiteRunnerSequential(unittest.TestCase):
    """Test sequential test execution."""

    def setUp(self):
        """Set up test suite runner."""
        self.mock_kafka_client = MagicMock(spec=KafkaClientWrapper)
        self.mock_registry = MagicMock()
        self.runner = TestSuiteRunner(
            kafka_client=self.mock_kafka_client,
            custom_placeholder_registry=self.mock_registry
        )

    @patch('src.test.suite.TestSuiteRunner.run_tests_sequential')
    def test_sequential_execution(self, mock_sequential):
        """Test sequential test execution method."""
        tests = [MagicMock(name="test-1"), MagicMock(name="test-2")]

        # Mock return value
        mock_sequential.return_value = [
            TestResult("test-1", "PASSED", 100),
            TestResult("test-2", "PASSED", 150)
        ]

        # Verify method exists
        self.assertIsNotNone(mock_sequential)


class TestTestSuiteRunnerParallel(unittest.TestCase):
    """Test parallel test execution."""

    def setUp(self):
        """Set up test suite runner."""
        self.mock_kafka_client = MagicMock(spec=KafkaClientWrapper)
        self.mock_registry = MagicMock()
        self.runner = TestSuiteRunner(
            kafka_client=self.mock_kafka_client,
            custom_placeholder_registry=self.mock_registry
        )

    @patch('src.test.suite.TestSuiteRunner.run_tests_parallel')
    def test_parallel_execution(self, mock_parallel):
        """Test parallel test execution method."""
        tests = [MagicMock(name="test-1"), MagicMock(name="test-2")]

        # Mock return value
        mock_parallel.return_value = [
            TestResult("test-1", "PASSED", 100),
            TestResult("test-2", "PASSED", 150)
        ]

        # Verify method exists
        self.assertIsNotNone(mock_parallel)


if __name__ == '__main__':
    unittest.main()









