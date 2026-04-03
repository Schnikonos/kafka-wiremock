#!/usr/bin/env python3
"""
Unit tests for Kafka and FastAPI components using mocks.
Avoids needing actual Kafka or FastAPI running.
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.kafka_client import KafkaClientWrapper


class TestKafkaClientMocked(unittest.TestCase):
    """Test KafkaClientWrapper using mocks."""

    @patch('src.kafka_client.KafkaProducer')
    def test_kafka_client_initialization(self, mock_producer_class):
        """Test KafkaClientWrapper initializes producer."""
        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        client = KafkaClientWrapper("localhost:9092")

        self.assertIsNotNone(client.producer)
        mock_producer_class.assert_called_once()

    @patch('src.kafka_client.KafkaAdminClient')
    def test_verify_topic_exists_found(self, mock_admin_class):
        """Test verifying topic exists."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_admin.list_topics.return_value = {'test-topic', 'other-topic'}

        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()
            result = client._verify_topic_exists('test-topic')

        self.assertTrue(result)
        mock_admin.close.assert_called_once()

    @patch('src.kafka_client.KafkaAdminClient')
    def test_verify_topic_not_exists(self, mock_admin_class):
        """Test verifying topic doesn't exist."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_admin.list_topics.return_value = {'other-topic'}

        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()
            result = client._verify_topic_exists('missing-topic')

        self.assertFalse(result)

    @patch('src.kafka_client.KafkaAdminClient')
    def test_topic_cache(self, mock_admin_class):
        """Test topic verification caching."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_admin.list_topics.return_value = {'test-topic'}

        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()

            # First check - should call admin
            result1 = client._verify_topic_exists('test-topic')
            self.assertTrue(result1)
            call_count_1 = mock_admin.list_topics.call_count

            # Second check - should use cache
            result2 = client._verify_topic_exists('test-topic')
            self.assertTrue(result2)
            # Should not have called admin again (still 1 call)
            self.assertEqual(mock_admin.list_topics.call_count, call_count_1)

    def test_serialize_value_bytes(self):
        """Test serializing bytes value."""
        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()
            result = client._serialize_value(b'test')
            self.assertEqual(result, b'test')

    def test_serialize_value_string(self):
        """Test serializing string value."""
        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()
            result = client._serialize_value('test')
            self.assertEqual(result, b'test')

    def test_serialize_value_dict(self):
        """Test serializing dict value."""
        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()
            result = client._serialize_value({'key': 'value'})
            self.assertEqual(result, b'{"key": "value"}')

    @patch('src.kafka_client.KafkaProducer')
    @patch('src.kafka_client.KafkaAdminClient')
    def test_produce_message_success(self, mock_admin_class, mock_producer_class):
        """Test producing a message successfully."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_admin.list_topics.return_value = {'test-topic'}

        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        # Mock the send method to return a future
        mock_future = MagicMock()
        mock_metadata = MagicMock()
        mock_metadata.topic = 'test-topic'
        mock_metadata.partition = 0
        mock_metadata.offset = 42
        mock_future.get.return_value = mock_metadata
        mock_producer.send.return_value = mock_future

        client = KafkaClientWrapper()
        message_id = client.produce('test-topic', {'data': 'test'})

        self.assertIsNotNone(message_id)
        self.assertIn('test-topic-0-42', message_id)

    @patch('src.kafka_client.KafkaProducer')
    @patch('src.kafka_client.KafkaAdminClient')
    def test_produce_topic_not_exists(self, mock_admin_class, mock_producer_class):
        """Test producing to non-existent topic is skipped."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_admin.list_topics.return_value = {}  # No topics

        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        client = KafkaClientWrapper()
        message_id = client.produce('missing-topic', {'data': 'test'})

        self.assertIsNone(message_id)
        mock_producer.send.assert_not_called()

    @patch('src.kafka_client.KafkaConsumer')
    def test_consume_messages(self, mock_consumer_class):
        """Test consuming messages."""
        mock_consumer = MagicMock()
        mock_consumer_class.return_value = mock_consumer

        # Mock message
        mock_message = MagicMock()
        mock_message.timestamp = 1000
        mock_message.partition = 0
        mock_message.offset = 1
        mock_message.key = b'key1'
        mock_message.value = b'{"test": "data"}'
        mock_message.headers = [('header1', b'value1')]

        mock_consumer.__iter__.return_value = [mock_message]

        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()
            messages = client.consume('test-topic', max_messages=1)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['value'], {'test': 'data'})
        self.assertEqual(messages[0]['key'], 'key1')

    @patch('src.kafka_client.KafkaProducer')
    @patch('src.kafka_client.KafkaConsumer')
    def test_consume_latest_messages(self, mock_consumer_class, mock_producer_class):
        """Test consuming latest messages."""
        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        mock_consumer = MagicMock()
        mock_consumer_class.return_value = mock_consumer

        mock_message = MagicMock()
        mock_message.timestamp = 2000
        mock_message.partition = 0
        mock_message.offset = 10
        mock_message.key = None
        mock_message.value = b'{"latest": true}'
        mock_message.headers = []

        mock_consumer.__iter__.return_value = [mock_message]

        messages = KafkaClientWrapper.consume_latest(
            KafkaClientWrapper("localhost:9092"),
            'test-topic',
            max_messages=1
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['value'], {'latest': True})

    def test_deserialize_json_message(self):
        """Test deserializing JSON message."""
        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()

            mock_message = MagicMock()
            mock_message.timestamp = 1000
            mock_message.partition = 0
            mock_message.offset = 1
            mock_message.key = b'key1'
            mock_message.value = b'{"test": "value"}'
            mock_message.headers = []

            result = client._deserialize_message(mock_message)

            self.assertEqual(result['value'], {'test': 'value'})
            self.assertEqual(result['format'], 'json')

    def test_deserialize_binary_message(self):
        """Test deserializing binary message."""
        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()

            mock_message = MagicMock()
            mock_message.timestamp = 1000
            mock_message.partition = 0
            mock_message.offset = 1
            mock_message.key = None
            mock_message.value = b'\x00\x01\x02\x03'
            mock_message.headers = []

            result = client._deserialize_message(mock_message)

            self.assertEqual(result['format'], 'binary')
            self.assertIsNotNone(result['value'])

    @patch('src.kafka_client.KafkaProducer')
    def test_close_connections(self, mock_producer_class):
        """Test closing Kafka connections."""
        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        client = KafkaClientWrapper()
        client.close()

        mock_producer.close.assert_called_once()


class TestKafkaClientEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    @patch('src.kafka_client.KafkaProducer')
    def test_produce_with_headers(self, mock_producer_class):
        """Test producing message with headers."""
        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer

        mock_future = MagicMock()
        mock_metadata = MagicMock()
        mock_metadata.topic = 'test'
        mock_metadata.partition = 0
        mock_metadata.offset = 1
        mock_future.get.return_value = mock_metadata
        mock_producer.send.return_value = mock_future

        with patch('src.kafka_client.KafkaAdminClient') as mock_admin_class:
            mock_admin = MagicMock()
            mock_admin_class.return_value = mock_admin
            mock_admin.list_topics.return_value = {'test'}

            client = KafkaClientWrapper()
            headers = {'X-Custom': 'value', 'X-Number': '123'}
            message_id = client.produce('test', {'msg': 'test'}, headers=headers)

            self.assertIsNotNone(message_id)
            # Verify send was called with headers
            call_args = mock_producer.send.call_args
            self.assertIsNotNone(call_args[1]['headers'])

    @patch('src.kafka_client.KafkaProducer')
    @patch('src.kafka_client.KafkaAdminClient')
    def test_produce_error_handling(self, mock_admin_class, mock_producer_class):
        """Test error handling during produce."""
        mock_admin = MagicMock()
        mock_admin_class.return_value = mock_admin
        mock_admin.list_topics.return_value = {'test'}

        mock_producer = MagicMock()
        mock_producer_class.return_value = mock_producer
        mock_producer.send.side_effect = Exception("Send failed")

        client = KafkaClientWrapper()
        message_id = client.produce('test', {'msg': 'test'})

        self.assertIsNone(message_id)

    @patch('src.kafka_client.KafkaConsumer')
    def test_consume_error_handling(self, mock_consumer_class):
        """Test error handling during consume."""
        mock_consumer_class.side_effect = Exception("Connection failed")

        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()
            messages = client.consume('test')

        self.assertEqual(messages, [])

    @patch('src.kafka_client.KafkaProducer')
    def test_serialize_value_none(self, mock_producer_class):
        """Test serializing None value."""
        with patch('src.kafka_client.KafkaProducer'):
            client = KafkaClientWrapper()
            result = client._serialize_value(None)
            self.assertEqual(result, b'null')


if __name__ == '__main__':
    unittest.main()

