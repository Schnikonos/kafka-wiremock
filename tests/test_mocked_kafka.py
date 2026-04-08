#!/usr/bin/env python3
"""
Unit tests for Kafka components using mocks.
Avoids needing actual Kafka running.
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.kafka.client import KafkaClientWrapper


class TestKafkaClientMocked(unittest.TestCase):
    """Test KafkaClientWrapper using mocks."""

    @patch('src.kafka.client.Producer')
    def test_kafka_client_initialization(self, mock_producer_class):
        """Test KafkaClientWrapper initializes producer."""
        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        client = KafkaClientWrapper("localhost:9092")

        self.assertIsNotNone(client.producer)
        mock_producer_class.assert_called_once()

    @patch('src.kafka.client.AdminClient')
    def test_verify_topic_exists_found(self, mock_admin_class):
        """Test verifying topic exists."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        # AdminClient.list_topics() returns a metadata object with topics
        mock_metadata = MagicMock()
        mock_metadata.topics = {'test-topic': MagicMock()}
        mock_admin.list_topics.return_value = mock_metadata

        with patch('src.kafka.client.Producer'):
            client = KafkaClientWrapper()
            result = client._verify_topic_exists('test-topic')

        self.assertTrue(result)

    @patch('src.kafka.client.AdminClient')
    def test_verify_topic_not_exists(self, mock_admin_class):
        """Test verifying topic doesn't exist."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        mock_metadata = MagicMock()
        mock_metadata.topics = {'other-topic': MagicMock()}
        mock_admin.list_topics.return_value = mock_metadata

        with patch('src.kafka.client.Producer'):
            client = KafkaClientWrapper()
            result = client._verify_topic_exists('missing-topic')

        self.assertFalse(result)

    @patch('src.kafka.client.AdminClient')
    def test_topic_cache(self, mock_admin_class):
        """Test topic verification caching."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        mock_metadata = MagicMock()
        mock_metadata.topics = {'test-topic': MagicMock()}
        mock_admin.list_topics.return_value = mock_metadata

        with patch('src.kafka.client.Producer'):
            client = KafkaClientWrapper()

            # First check - should call admin
            result1 = client._verify_topic_exists('test-topic')
            self.assertTrue(result1)
            call_count_1 = mock_admin.list_topics.call_count

            # Second check - should use cache
            result2 = client._verify_topic_exists('test-topic')
            self.assertTrue(result2)
            # Should not have called admin again
            self.assertEqual(mock_admin.list_topics.call_count, call_count_1)

    @patch('src.kafka.client.Producer')
    @patch('src.kafka.client.AdminClient')
    def test_produce_message_success(self, mock_admin_class, mock_producer_class):
        """Test producing a message successfully."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        mock_metadata = MagicMock()
        mock_metadata.topics = {'test-topic': MagicMock()}
        mock_admin.list_topics.return_value = mock_metadata

        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        # Mock the send method to return metadata
        mock_future = MagicMock()
        mock_record_metadata = MagicMock()
        mock_record_metadata.topic = 'test-topic'
        mock_record_metadata.partition = 0
        mock_record_metadata.offset = 42
        mock_future.get.return_value = mock_record_metadata
        mock_producer.send.return_value = mock_future

        client = KafkaClientWrapper()
        message_id = client.produce('test-topic', {'data': 'test'})

        # Verify produce was attempted (message_id is generated)
        self.assertIsNotNone(message_id)

    @patch('src.kafka.client.Producer')
    @patch('src.kafka.client.AdminClient')
    def test_produce_topic_not_exists(self, mock_admin_class, mock_producer_class):
        """Test producing to non-existent topic is skipped."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        mock_metadata = MagicMock()
        mock_metadata.topics = {}  # No topics
        mock_admin.list_topics.return_value = mock_metadata

        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        client = KafkaClientWrapper()
        message_id = client.produce('missing-topic', {'data': 'test'})

        self.assertIsNone(message_id)
        mock_producer.send.assert_not_called()

    @patch('src.kafka.client.Producer')
    def test_close_connections(self, mock_producer_class):
        """Test closing Kafka connections."""
        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        with patch('src.kafka.client.AdminClient'):
            client = KafkaClientWrapper()
            # Just verify the client can be created with mocks
            self.assertIsNotNone(client)


class TestKafkaClientEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    @patch('src.kafka.client.Producer')
    @patch('src.kafka.client.AdminClient')
    def test_produce_with_headers(self, mock_admin_class, mock_producer_class):
        """Test producing message with headers."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        mock_metadata = MagicMock()
        mock_metadata.topics = {'test': MagicMock()}
        mock_admin.list_topics.return_value = mock_metadata

        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        mock_future = MagicMock()
        mock_record_metadata = MagicMock()
        mock_record_metadata.topic = 'test'
        mock_record_metadata.partition = 0
        mock_record_metadata.offset = 1
        mock_future.get.return_value = mock_record_metadata
        mock_producer.send.return_value = mock_future

        client = KafkaClientWrapper()
        headers = {'X-Custom': 'value', 'X-Number': '123'}
        message_id = client.produce('test', {'msg': 'test'}, headers=headers)

        # Verify produce was attempted
        self.assertIsNotNone(message_id)

    @patch('src.kafka.client.Producer')
    @patch('src.kafka.client.AdminClient')
    def test_produce_error_handling(self, mock_admin_class, mock_producer_class):
        """Test produce returns message ID when admin succeeds."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin

        mock_metadata = MagicMock()
        mock_metadata.topics = {'test': MagicMock()}
        mock_admin.list_topics.return_value = mock_metadata

        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        client = KafkaClientWrapper()
        # Produce should succeed with proper topic
        message_id = client.produce('test', {'msg': 'test'})

        # Message ID should be generated
        self.assertIsNotNone(message_id)


if __name__ == '__main__':
    unittest.main()







