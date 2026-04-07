"""
Schema Registry integration for AVRO encoding/decoding.
Interfaces with Confluent Schema Registry and caches schemas.
"""
import logging
import json
import io
import struct
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import threading

try:
    import fastavro
    AVRO_AVAILABLE = True
except ImportError:
    AVRO_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)


class CachedSchema:
    """A cached schema with TTL."""

    def __init__(self, schema_id: int, schema: Dict[str, Any], ttl_seconds: int = 3600):
        self.schema_id = schema_id
        self.schema = schema
        self.cached_at = datetime.now()
        self.ttl_seconds = ttl_seconds

    def is_expired(self) -> bool:
        """Check if schema cache has expired."""
        return datetime.now() - self.cached_at > timedelta(seconds=self.ttl_seconds)


class SchemaRegistry:
    """
    Interfaces with Confluent Schema Registry for AVRO schema caching and encoding/decoding.
    Gracefully degrades if registry is unavailable.
    """

    def __init__(self, registry_url: Optional[str] = None, cache_ttl_seconds: int = 3600):
        """
        Initialize Schema Registry client.

        Args:
            registry_url: Confluent Schema Registry URL (e.g., http://localhost:8081)
                         If not provided, AVRO operations will be limited (no schema lookup)
            cache_ttl_seconds: How long to cache schemas (default 1 hour)
        """
        self.registry_url = registry_url
        self.cache_ttl_seconds = cache_ttl_seconds
        self.schema_cache: Dict[int, CachedSchema] = {}
        self._lock = threading.Lock()
        self._available = False

        if self.registry_url and REQUESTS_AVAILABLE:
            self._test_connection()

    def _test_connection(self) -> None:
        """Test connection to schema registry."""
        if not self.registry_url or not REQUESTS_AVAILABLE:
            return

        try:
            response = requests.get(
                f"{self.registry_url}/subjects",
                timeout=5,
                headers={"Accept": "application/vnd.schemaregistry.v1+json"}
            )
            if response.status_code in (200, 404):  # 404 means no subjects yet, but registry is up
                self._available = True
                logger.info(f"Schema Registry connected: {self.registry_url}")
            else:
                logger.warning(f"Schema Registry returned status {response.status_code}")
        except Exception as e:
            logger.warning(f"Could not connect to Schema Registry at {self.registry_url}: {e}")
            self._available = False

    def decode(self, payload: bytes, schema_id: Optional[int] = None) -> tuple:
        """
        Decode an AVRO message.

        Args:
            payload: Raw message bytes (may include Confluent magic byte)
            schema_id: Optional schema ID (extracted from payload if not provided)

        Returns:
            Tuple of (decoded_value, format_type) where format_type is "avro" or "error"
            Returns (None, "error") if decoding fails
        """
        if not AVRO_AVAILABLE:
            logger.debug("fastavro not available for decoding")
            return None, "error"

        try:
            # Check for Confluent magic byte (0x00) + 4-byte schema ID
            actual_schema_id = schema_id
            data_start = 0

            if len(payload) > 5 and payload[0:1] == b'\x00':
                # Confluent format with magic byte
                actual_schema_id = struct.unpack('>I', payload[1:5])[0]
                data_start = 5
                logger.debug(f"Detected Confluent AVRO format with schema ID: {actual_schema_id}")

            # Extract AVRO data
            avro_data = payload[data_start:]
            bytes_reader = io.BytesIO(avro_data)

            # If we have a schema ID, try to get the schema
            if actual_schema_id:
                schema = self._get_schema(actual_schema_id)
                if schema:
                    value = fastavro.reader(bytes_reader, reader_schema=schema).__next__()
                else:
                    # Fallback: decode without reader schema
                    value = fastavro.reader(bytes_reader).__next__()
            else:
                # No schema ID available, decode raw
                value = fastavro.reader(bytes_reader).__next__()

            return value, "avro"

        except Exception as e:
            logger.debug(f"AVRO decode failed: {e}")
            return None, "error"

    def encode(self, payload: Any, schema_id: Optional[int] = None) -> Optional[bytes]:
        """
        Encode a message as AVRO with Confluent magic byte.

        Args:
            payload: Dictionary or value to encode
            schema_id: Schema ID to use

        Returns:
            Encoded bytes with Confluent magic byte prefix, or None if encoding fails
        """
        if not AVRO_AVAILABLE:
            logger.warning("fastavro not available for encoding")
            return None

        if schema_id is None:
            logger.warning("Schema ID required for AVRO encoding")
            return None

        try:
            schema = self._get_schema(schema_id)
            if not schema:
                logger.error(f"Could not retrieve schema {schema_id}")
                return None

            # Encode with fastavro
            bytes_writer = io.BytesIO()
            fastavro.schemaless_writer(bytes_writer, schema, payload)
            avro_bytes = bytes_writer.getvalue()

            # Prepend Confluent magic byte + schema ID
            magic_byte = b'\x00'
            schema_id_bytes = struct.pack('>I', schema_id)
            encoded = magic_byte + schema_id_bytes + avro_bytes

            logger.debug(f"Encoded message with schema ID {schema_id}: {len(encoded)} bytes")
            return encoded

        except Exception as e:
            logger.error(f"AVRO encode failed: {e}")
            return None

    def _get_schema(self, schema_id: int) -> Optional[Dict[str, Any]]:
        """
        Get schema by ID, with caching.

        Args:
            schema_id: Schema ID

        Returns:
            Schema dict or None if not found
        """
        with self._lock:
            # Check cache
            if schema_id in self.schema_cache:
                cached = self.schema_cache[schema_id]
                if not cached.is_expired():
                    logger.debug(f"Using cached schema {schema_id}")
                    return cached.schema
                else:
                    del self.schema_cache[schema_id]

        # Fetch from registry
        schema = self._fetch_schema_from_registry(schema_id)

        if schema:
            with self._lock:
                self.schema_cache[schema_id] = CachedSchema(
                    schema_id,
                    schema,
                    ttl_seconds=self.cache_ttl_seconds
                )

        return schema

    def _fetch_schema_from_registry(self, schema_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch schema from Schema Registry.

        Args:
            schema_id: Schema ID

        Returns:
            Schema dict or None if fetch fails
        """
        if not self._available or not REQUESTS_AVAILABLE:
            logger.debug(f"Schema Registry not available, cannot fetch schema {schema_id}")
            return None

        try:
            url = f"{self.registry_url}/schemas/ids/{schema_id}"
            response = requests.get(
                url,
                timeout=5,
                headers={"Accept": "application/vnd.schemaregistry.v1+json"}
            )

            if response.status_code == 200:
                data = response.json()
                schema_str = data.get('schema')
                if schema_str:
                    schema = json.loads(schema_str)
                    logger.info(f"Fetched schema {schema_id} from registry")
                    return schema
            else:
                logger.warning(f"Schema Registry returned status {response.status_code} for schema {schema_id}")

        except Exception as e:
            logger.warning(f"Failed to fetch schema {schema_id} from registry: {e}")

        return None

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            expired_count = sum(1 for c in self.schema_cache.values() if c.is_expired())
            valid_count = len(self.schema_cache) - expired_count

            return {
                "registry_url": self.registry_url,
                "available": self._available,
                "cached_schemas": valid_count,
                "expired_schemas": expired_count,
                "cache_ttl_seconds": self.cache_ttl_seconds
            }


