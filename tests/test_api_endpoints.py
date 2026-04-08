#!/usr/bin/env python3
"""
Unit tests for FastAPI endpoints and API modules.
Tests all endpoint routes using FastAPI's TestClient.
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from src.main import app


class TestAPIEndpoints(unittest.TestCase):
    """Test FastAPI endpoints."""

    def setUp(self):
        """Set up test client."""
        self.client = TestClient(app)

    def test_health_check(self):
        """Test health check endpoint."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")

    @patch('src.api.kafka_injection._kafka_client', None)
    def test_inject_message_no_client(self):
        """Test inject endpoint when client not initialized."""
        response = self.client.post("/inject/test-topic", json={"message": {"test": "data"}})
        self.assertEqual(response.status_code, 503)

    @patch('src.api.kafka_injection._kafka_client', None)
    def test_get_messages_no_client(self):
        """Test get messages endpoint when client not initialized."""
        response = self.client.get("/messages/test-topic")
        self.assertEqual(response.status_code, 503)

    @patch('src.api.rules._config_loader', None)
    def test_get_rules_no_loader(self):
        """Test rules endpoint when loader not initialized."""
        response = self.client.get("/rules")
        self.assertEqual(response.status_code, 503)

    @patch('src.api.rules._config_loader', None)
    def test_get_rules_by_topic_no_loader(self):
        """Test rules by topic endpoint when loader not initialized."""
        response = self.client.get("/rules/test-topic")
        self.assertEqual(response.status_code, 503)

    @patch('src.api.custom_placeholders._custom_placeholder_registry', None)
    def test_get_custom_placeholders_no_registry(self):
        """Test custom placeholders endpoint when registry not initialized."""
        response = self.client.get("/custom-placeholders")
        self.assertEqual(response.status_code, 503)

    @patch('src.api.dependencies_mgmt._dependency_manager', None)
    def test_get_dependencies_no_manager(self):
        """Test dependencies endpoint when manager not initialized."""
        response = self.client.get("/dependencies")
        self.assertEqual(response.status_code, 503)

    @patch('src.api.tests.discovery._test_loader', None)
    def test_list_tests_no_loader(self):
        """Test list tests endpoint when loader not initialized."""
        response = self.client.get("/tests")
        self.assertEqual(response.status_code, 503)

    @patch('src.api.tests.discovery._test_loader', None)
    def test_get_test_definition_no_loader(self):
        """Test get test endpoint when loader not initialized."""
        response = self.client.get("/tests/test-id")
        self.assertEqual(response.status_code, 503)

    @patch('src.api.tests.execution._test_loader', None)
    def test_run_single_test_no_loader(self):
        """Test run test endpoint when loader not initialized."""
        response = self.client.post("/tests/test-id")
        self.assertEqual(response.status_code, 503)

    @patch('src.api.tests.execution._test_loader', None)
    def test_run_tests_bulk_no_loader(self):
        """Test bulk test endpoint when loader not initialized."""
        response = self.client.post("/tests:bulk")
        self.assertEqual(response.status_code, 503)

    @patch('src.api.tests.jobs._test_job_manager', None)
    def test_get_job_status_no_manager(self):
        """Test get job status endpoint when manager not initialized."""
        response = self.client.get("/tests/jobs/job-id")
        self.assertEqual(response.status_code, 503)

    @patch('src.api.tests.jobs._test_job_manager', None)
    def test_list_jobs_no_manager(self):
        """Test list jobs endpoint when manager not initialized."""
        response = self.client.get("/tests/jobs")
        self.assertEqual(response.status_code, 503)

    def test_list_test_logs(self):
        """Test list logs endpoint."""
        response = self.client.get("/tests/logs")
        # Endpoint should return either 200 or 503 depending on app state
        self.assertIn(response.status_code, [200, 503])

    def test_get_test_log_not_found(self):
        """Test get log endpoint for non-existent test."""
        response = self.client.get("/tests/logs/nonexistent-test")
        self.assertEqual(response.status_code, 404)

    @patch('src.api.rules._config_loader', None)
    @patch('src.api.rules._listener_engine', None)
    def test_explain_rule_match_no_services(self):
        """Test explain rule match endpoint when services not initialized."""
        response = self.client.post("/rules:match", params={"topic": "test"}, json={"message": "test"})
        self.assertEqual(response.status_code, 503)

    @patch('src.api.debug.decode._listener_engine', None)
    def test_debug_decode_no_engine(self):
        """Test debug decode endpoint when engine not initialized."""
        response = self.client.post("/debug/decode", json={"topic": "test", "payload": "test"})
        self.assertEqual(response.status_code, 503)

    @patch('src.api.debug.match._config_loader', None)
    def test_debug_match_no_loader(self):
        """Test debug match endpoint when loader not initialized."""
        response = self.client.post("/debug/match", json={"topic": "test", "payload": {}})
        self.assertEqual(response.status_code, 503)

    @patch('src.api.debug.topics._listener_engine', None)
    def test_debug_topics_no_engine(self):
        """Test debug topics endpoint when engine not initialized."""
        response = self.client.get("/debug/topics")
        self.assertEqual(response.status_code, 200)

    @patch('src.api.debug.cache._message_cache', None)
    def test_debug_cache_no_cache(self):
        """Test debug cache endpoint when cache not initialized."""
        response = self.client.get("/debug/cache")
        self.assertEqual(response.status_code, 503)

    def test_debug_template_render(self):
        """Test debug template render endpoint."""
        response = self.client.post(
            "/debug/template/render",
            json={"template": "Hello {{name}}", "context": {"name": "World"}}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("rendered", data)

    def test_openapi_docs_available(self):
        """Test OpenAPI documentation endpoint."""
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()


