"""
Send definition loader for simple message injection.
Parses send YAML files that contain only injection blocks (no test assertions).
"""
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Union
from dataclasses import dataclass, field
from src.test.loader import TestInjection, TestScript, TestYamlParser
from src.config.models import Fault

logger = logging.getLogger(__name__)


@dataclass
class SendDefinition:
    """A send definition - simple message injection(s) with optional scripts."""
    name: str  # Send identifier
    items: List[Union[TestInjection, TestScript]] = field(default_factory=list)  # Mixed items, executed sequentially
    priority: int = 999  # Optional; lower = runs first
    tags: List[str] = field(default_factory=list)  # Optional; for filtering
    skip: bool = False  # Optional; default false
    timeout_ms: int = 5000  # Optional; overall timeout
    file_path: Optional[str] = None  # Path to the send YAML file (for logging)


class SendYamlParser:
    """Parses send YAML files."""

    @staticmethod
    def parse_send_yaml(yaml_content: str, file_path: str = "unknown") -> Dict[str, Any]:
        """
        Parse send YAML content.

        Args:
            yaml_content: YAML string content
            file_path: Path to YAML file (for error reporting)

        Returns:
            Parsed YAML as dictionary

        Raises:
            yaml.YAMLError: If YAML is invalid
        """
        try:
            data = yaml.safe_load(yaml_content)
            if not isinstance(data, dict):
                raise ValueError(f"Send YAML must be a dictionary at root level, got {type(data)}")
            return data
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {file_path}: {e}")


class SendValidator:
    """Validates send definitions."""

    @staticmethod
    def validate_send_definition(send_dict: Dict[str, Any], file_path: str = "unknown") -> SendDefinition:
        """
        Validate and convert send dictionary to SendDefinition.

        Args:
            send_dict: Parsed YAML dictionary
            file_path: Path to YAML file (for error reporting)

        Returns:
            SendDefinition object

        Raises:
            ValueError: If validation fails
        """
        try:
            # Validate required fields
            if "name" not in send_dict:
                raise ValueError("Missing required field: 'name'")
            if "inject" not in send_dict:
                raise ValueError("Missing required field: 'inject'")

            name = str(send_dict["name"])
            priority = int(send_dict.get("priority", 999))
            tags = send_dict.get("tags", [])
            skip = bool(send_dict.get("skip", False))
            timeout_ms = int(send_dict.get("timeout_ms", 5000))

            if not isinstance(tags, list):
                tags = [tags] if tags else []

            # Parse inject + script items (same format as test 'when' phase)
            inject_dict = send_dict.get("inject", [])
            items = SendValidator._parse_inject(inject_dict)

            logger.debug(f"Creating SendDefinition for {name} with file_path={file_path}")

            return SendDefinition(
                name=name,
                items=items,
                priority=priority,
                tags=tags,
                skip=skip,
                timeout_ms=timeout_ms,
                file_path=file_path
            )

        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"Invalid send definition in {file_path}: {e}")

    @staticmethod
    def _parse_inject(inject_list: List[Any]) -> List[Union[TestInjection, TestScript]]:
        """Parse inject list - can contain injections and scripts."""
        if not isinstance(inject_list, list):
            raise ValueError("'inject' must be a list")

        items = []
        for idx, item_dict in enumerate(inject_list):
            if not isinstance(item_dict, dict):
                raise ValueError(f"Inject item at index {idx} must be a dictionary")

            # Check if it's a script (inline or file-based)
            if "script" in item_dict and len(item_dict) == 1:
                # It's an inline script
                items.append(TestScript(script=str(item_dict["script"])))
            elif "script_file" in item_dict and len(item_dict) == 1:
                # It's a script file reference
                items.append(TestScript(script="", script_file=str(item_dict["script_file"])))
            else:
                # It's an injection
                if "message_id" not in item_dict:
                    raise ValueError(f"Injection at index {idx} missing 'message_id'")
                if "destination" not in item_dict:
                    raise ValueError(f"Injection at index {idx} missing 'destination'")
                msg_type = str(item_dict.get("type", "kafka")).lower()
                if msg_type != "http" and "payload" not in item_dict and "payload_file" not in item_dict:
                    raise ValueError(f"Injection at index {idx} missing 'payload' or 'payload_file'")

                injection = TestInjection(
                    message_id=str(item_dict["message_id"]),
                    destination=str(item_dict["destination"]),
                    payload=str(item_dict["payload"]) if "payload" in item_dict else None,
                    payload_file=item_dict.get("payload_file"),
                    headers=item_dict.get("headers"),
                    key=item_dict.get("key"),
                    delay_ms=int(item_dict.get("delay_ms", 0)),
                    correlation_id=item_dict.get("correlation_id"),
                    fault=TestYamlParser._parse_fault(item_dict.get("fault")),
                    msg_type=msg_type,
                    connection_ref=item_dict.get("connection_ref"),
                    method=str(item_dict.get("method", "POST")).upper(),
                    query_params=item_dict.get("query_params"),
                    auth_ref=item_dict.get("auth_ref"),
                    tls_ref=item_dict.get("tls_ref"),
                    http_timeout_ms=int(item_dict.get("http_timeout_ms", 10000)),
                )
                items.append(injection)

        return items


class SendLoader:
    """Loads and discovers send definitions from /send/ directory."""

    def __init__(self, send_dir: str = "/send"):
        """
        Initialize send loader.

        Args:
            send_dir: Path to send directory
        """
        self.send_dir = Path(send_dir)
        self.send_dir.mkdir(parents=True, exist_ok=True)
        # Track validation errors per file
        self.validation_errors: Dict[str, List[str]] = {}
        # Cache for send discovery
        self._cached_sends: Optional[List[SendDefinition]] = None
        self._cached_send_files: Optional[Set[str]] = None

    def discover_sends(self) -> List[SendDefinition]:
        """
        Discover and load all send files from /send/ directory.
        Uses caching to avoid repeated logging when send files haven't changed.

        Returns:
            List of SendDefinition objects, sorted by priority
        """
        # Build {path: mtime} dict — detects both new/removed files AND edits
        yaml_files = sorted(self.send_dir.rglob("*.send.yaml")) + \
                     sorted(self.send_dir.rglob("*.send.yml"))
        current_files = {str(f): f.stat().st_mtime for f in yaml_files}

        # Cache hit: same files AND none of them were modified
        if self._cached_sends is not None and self._cached_send_files == current_files:
            return self._cached_sends

        # Sends have changed, reload them
        sends = []

        if not yaml_files:
            logger.debug(f"No send files found in {self.send_dir}")
            self._cached_sends = sends
            self._cached_send_files = current_files
            return sends

        for yaml_file in yaml_files:
            try:
                send = self.load_send_file(yaml_file)
                sends.append(send)
                logger.info(f"Loaded send: {send.name} from {yaml_file}")
                logger.debug(f"  Send file_path: {send.file_path}")
            except Exception as e:
                logger.error(f"Failed to load send {yaml_file.name}: {e}")

        # Sort by priority (lower = first) then by name
        sends.sort(key=lambda s: (s.priority, s.name))
        logger.info(f"Discovered {len(sends)} sends")

        # Cache the results
        self._cached_sends = sends
        self._cached_send_files = current_files
        return sends

    def load_send_file(self, file_path: Path) -> SendDefinition:
        """
        Load a single send file.

        Args:
            file_path: Path to send YAML file

        Returns:
            SendDefinition object

        Raises:
            ValueError: If file is invalid
        """
        try:
            with open(file_path, "r") as f:
                yaml_content = f.read()

            send_dict = SendYamlParser.parse_send_yaml(yaml_content, str(file_path))
            send = SendValidator.validate_send_definition(send_dict, str(file_path))

            # Resolve payload files and script files relative to send file directory
            send_dir = Path(file_path).parent
            self._resolve_payload_files(send, send_dir)
            self._resolve_script_files(send, send_dir)

            return send
        except Exception as e:
            raise ValueError(f"Failed to load send from {file_path}: {e}")

    def _resolve_payload_files(self, send: SendDefinition, send_file_dir: Path):
        """
        Resolve external payload files in send definition.

        Args:
            send: Send definition to resolve
            send_file_dir: Directory where send file is located
        """
        for item in send.items:
            if isinstance(item, TestInjection) and item.payload_file:
                payload_path = send_file_dir / item.payload_file
                if not payload_path.exists():
                    logger.warning(f"Payload file not found: {payload_path}")
                else:
                    try:
                        with open(payload_path, "r") as f:
                            item.payload = f.read()
                        logger.debug(f"Loaded payload from {item.payload_file}")
                    except Exception as e:
                        logger.error(f"Failed to load payload file {item.payload_file}: {e}")

    def _resolve_script_files(self, send: SendDefinition, send_file_dir: Path):
        """
        Resolve external script files in send definition.

        Args:
            send: Send definition to resolve
            send_file_dir: Directory where send file is located
        """
        for item in send.items:
            if isinstance(item, TestScript) and item.script_file:
                script_path = send_file_dir / item.script_file
                if not script_path.exists():
                    logger.warning(f"Script file not found: {script_path}")
                else:
                    try:
                        with open(script_path, "r") as f:
                            item.script = f.read()
                        logger.debug(f"Loaded script from {item.script_file}")
                    except Exception as e:
                        logger.error(f"Failed to load script file {item.script_file}: {e}")

    def get_sends_by_tag(self, sends: List[SendDefinition], tags: List[str]) -> List[SendDefinition]:
        """
        Filter sends by tags (OR logic - send matches if it has any of the requested tags).

        Args:
            sends: List of SendDefinition objects
            tags: List of tag filters

        Returns:
            Filtered list of SendDefinition objects
        """
        if not tags:
            return sends
        return [s for s in sends if any(tag in s.tags for tag in tags)]
