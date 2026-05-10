"""
JSON schema validator for YAML configuration files.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
import jsonschema

logger = logging.getLogger(__name__)


class SchemaValidator:
    """Validates YAML configurations against JSON schemas."""

    def __init__(self):
        """Initialize validator with schema cache."""
        self._schemas: Dict[str, Dict[str, Any]] = {}
        self._schema_dir = Path(__file__).parent.parent.parent  # Project root
        self._load_schemas()

    def _load_schemas(self) -> None:
        """Load all JSON schemas from project root."""
        schema_files = {
            "rule": "rule-schema.json",
            "test": "test-suite-schema.json",
            "send": "send-schema.json",
            "jms_config": "jms-config-schema.json",
            "topic_config": "topic-config-schema.json"
        }

        for schema_name, schema_file in schema_files.items():
            schema_path = self._schema_dir / schema_file
            if schema_path.exists():
                try:
                    with open(schema_path, 'r') as f:
                        self._schemas[schema_name] = json.load(f)
                    logger.debug(f"Loaded schema: {schema_name}")
                except Exception as e:
                    logger.warning(f"Failed to load schema {schema_name}: {e}")
            else:
                logger.debug(f"Schema file not found: {schema_path}")

    def validate_rule(self, rule_data: Dict[str, Any], filename: str = "unknown") -> List[str]:
        """
        Validate a rule against rule schema.

        Args:
            rule_data: Rule data dictionary
            filename: Filename for error messages

        Returns:
            List of validation errors (empty if valid)
        """
        return self._validate(rule_data, "rule", filename)

    def validate_test(self, test_data: Dict[str, Any], filename: str = "unknown") -> List[str]:
        """
        Validate a test against test schema.

        Args:
            test_data: Test data dictionary
            filename: Filename for error messages

        Returns:
            List of validation errors (empty if valid)
        """
        return self._validate(test_data, "test", filename)

    def validate_send(self, send_data: Dict[str, Any], filename: str = "unknown") -> List[str]:
        """
        Validate a send operation against send schema.

        Args:
            send_data: Send data dictionary
            filename: Filename for error messages

        Returns:
            List of validation errors (empty if valid)
        """
        return self._validate(send_data, "send", filename)

    def validate_jms_config(self, jms_data: Dict[str, Any], filename: str = "unknown") -> List[str]:
        """
        Validate JMS configuration against jms-config schema.

        Args:
            jms_data: JMS config data dictionary
            filename: Filename for error messages

        Returns:
            List of validation errors (empty if valid)
        """
        return self._validate(jms_data, "jms_config", filename)

    def validate_topic_config(self, topic_data: Dict[str, Any], filename: str = "unknown") -> List[str]:
        """
        Validate topic configuration against topic-config schema.

        Args:
            topic_data: Topic config data dictionary
            filename: Filename for error messages

        Returns:
            List of validation errors (empty if valid)
        """
        return self._validate(topic_data, "topic_config", filename)

    def _validate(self, data: Dict[str, Any], schema_name: str, filename: str) -> List[str]:
        """
        Validate data against a schema.

        Args:
            data: Data to validate
            schema_name: Schema name (e.g., 'rule', 'test')
            filename: Filename for error messages

        Returns:
            List of validation errors
        """
        if schema_name not in self._schemas:
            logger.warning(f"Schema '{schema_name}' not loaded")
            return []

        errors = []
        try:
            jsonschema.validate(instance=data, schema=self._schemas[schema_name])
        except jsonschema.ValidationError as e:
            error_path = " → ".join(str(p) for p in e.absolute_path) if e.absolute_path else "root"
            errors.append(f"{filename}: {error_path}: {e.message}")
        except jsonschema.SchemaError as e:
            errors.append(f"{filename}: Schema error: {e.message}")
        except Exception as e:
            errors.append(f"{filename}: Validation error: {e}")

        return errors

    def get_schema(self, schema_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a schema by name.

        Args:
            schema_name: Schema name

        Returns:
            Schema dictionary or None if not found
        """
        return self._schemas.get(schema_name)

    def list_available_schemas(self) -> List[str]:
        """List all available schema names."""
        return list(self._schemas.keys())

