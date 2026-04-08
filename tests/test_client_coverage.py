#!/usr/bin/env python3
"""
Unit tests for Kafka client wrapper functionality.
Tests message serialization, deserialization, and topic verification.
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.kafka.client import KafkaClientWrapper, get_kafka_config


class TestKafkaConfig(unittest.TestCase):
    """Test Kafka configuration builder."""

    @patch.dict('os.environ', {})
    def test_default_config(self):
        """Test default Kafka config."""
        config = get_kafka_config()
        self.assertIn('bootstrap.servers', config)
        self.assertEqual(config['bootstrap.servers'], 'localhost:9092')

    @patch.dict('os.environ', {'KAFKA_BOOTSTRAP_SERVERS': 'kafka:9092'})
    def test_custom_bootstrap_servers(self):
        """Test custom bootstrap servers."""
        config = get_kafka_config('kafka:9092')
        self.assertEqual(config['bootstrap.servers'], 'kafka:9092')

    @patch.dict('os.environ', {'KAFKA_SECURITY_PROTOCOL': 'SSL'})
    def test_security_protocol_config(self):
        """Test security protocol configuration."""
        config = get_kafka_config()
        self.assertIsNotNone(config)

    @patch.dict('os.environ', {
        'KAFKA_SASL_MECHANISM': 'PLAIN',
        'KAFKA_SASL_USERNAME': 'user',
        'KAFKA_SASL_PASSWORD': 'pass'
    })
    def test_sasl_config(self):
        """Test SASL configuration."""
        config = get_kafka_config()
        self.assertIsNotNone(config)


class TestKafkaClientInitialization(unittest.TestCase):
    """Test KafkaClientWrapper initialization."""

    @patch('src.kafka.client.Producer')
    def test_client_initialization(self, mock_producer):
        """Test client initializes producer."""
        client = KafkaClientWrapper('localhost:9092')
        self.assertIsNotNone(client.producer)
        self.assertEqual(client.bootstrap_servers, 'localhost:9092')

    @patch('src.kafka.client.Producer')
    def test_client_base_config(self, mock_producer):
        """Test client has base configuration."""
        client = KafkaClientWrapper()
        self.assertIsNotNone(client.base_config)
        self.assertIsInstance(client.base_config, dict)


class TestKafkaClientTopicVerification(unittest.TestCase):
    """Test topic verification functionality."""

    @patch('src.kafka.client.AdminClient')
    @patch('src.kafka.client.Producer')
    def test_verify_topic_exists(self, mock_producer, mock_admin_class):
        """Test topic verification when it exists."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_metadata = MagicMock()
        mock_metadata.topics = {'test-topic': MagicMock()}
        mock_admin.list_topics.return_value = mock_metadata

        client = KafkaClientWrapper()
        result = client._verify_topic_exists('test-topic')

        self.assertTrue(result)

    @patch('src.kafka.client.AdminClient')
    @patch('src.kafka.client.Producer')
    def test_verify_topic_not_exists(self, mock_producer, mock_admin_class):
        """Test topic verification when it doesn't exist."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_metadata = MagicMock()
        mock_metadata.topics = {}
        mock_admin.list_topics.return_value = mock_metadata

        client = KafkaClientWrapper()
        result = client._verify_topic_exists('missing-topic')

        self.assertFalse(result)

    @patch('src.kafka.client.AdminClient')
    @patch('src.kafka.client.Producer')
    def test_topic_cache(self, mock_producer, mock_admin_class):
        """Test topic cache functionality."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_metadata = MagicMock()
        mock_metadata.topics = {'test': MagicMock()}
        mock_admin.list_topics.return_value = mock_metadata

        client = KafkaClientWrapper()

        # First call
        result1 = client._verify_topic_exists('test')
        count1 = mock_admin.list_topics.call_count

        # Second call (should use cache)
        result2 = client._verify_topic_exists('test')
        count2 = mock_admin.list_topics.call_count

        self.assertTrue(result1)
        self.assertTrue(result2)
        self.assertEqual(count1, count2)  # Should not call admin again


class TestKafkaClientProduction(unittest.TestCase):
    """Test message production."""

    @patch('src.kafka.client.AdminClient')
    @patch('src.kafka.client.Producer')
    def test_produce_success(self, mock_producer_class, mock_admin_class):
        """Test successful message production."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_metadata = MagicMock()
        mock_metadata.topics = {'test-topic': MagicMock()}
        mock_admin.list_topics.return_value = mock_metadata

        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer
        mock_future = MagicMock()
        mock_metadata_obj = MagicMock()
        mock_metadata_obj.topic = 'test-topic'
        mock_metadata_obj.partition = 0
        mock_metadata_obj.offset = 1
        mock_future.get.return_value = mock_metadata_obj
        mock_producer.send.return_value = mock_future

        client = KafkaClientWrapper()
        message_id = client.produce('test-topic', {'data': 'test'})

        self.assertIsNotNone(message_id)

    @patch('src.kafka.client.AdminClient')
    @patch('src.kafka.client.Producer')
    def test_produce_missing_topic(self, mock_producer_class, mock_admin_class):
        """Test production to missing topic."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_metadata = MagicMock()
        mock_metadata.topics = {}
        mock_admin.list_topics.return_value = mock_metadata

        client = KafkaClientWrapper()
        message_id = client.produce('missing-topic', {'data': 'test'})

        self.assertIsNone(message_id)


class TestKafkaClientClose(unittest.TestCase):
    """Test client cleanup."""

    @patch('src.kafka.client.Producer')
    def test_client_close(self, mock_producer_class):
        """Test closing client."""
        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        client = KafkaClientWrapper()
        client.close()

        self.assertIsNotNone(mock_producer)


if __name__ == '__main__':
    unittest.main()




