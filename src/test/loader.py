"""
Test Suite YAML loader and validator.
Parses test definitions from YAML files in /testSuite/ directory.
"""
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Union
from dataclasses import dataclass, field
from src.config.models import Condition, Fault

logger = logging.getLogger(__name__)


@dataclass
class TestDBAction:
    """A database action in when.inject or then.expectations (type: db)."""
    id: str                                      # Step ID — stored in context as db.<id>.*
    db_ref: str                                  # Database reference name (from databases.yaml)
    operation: str                               # select | insert | update | delete
    query: str                                   # Raw SQL/CQL (template placeholders supported)
    params: Optional[Dict[str, Any]] = None      # Optional named bind params (also template-rendered)
    delay_ms: int = 0
    # For 'then' phase: optional match conditions on select results (DB assertion)
    match: List[Condition] = field(default_factory=list)
    # Expected row count (for select assertions in then phase; None = no check)
    expected_row_count: Optional[int] = None


@dataclass
class HttpInjectionResult:
    """Captured response from an HTTP injection (type=http)."""
    message_id: str
    status_code: int
    response_headers: Dict[str, str] = field(default_factory=dict)
    body: str = ""
    body_json: Optional[Any] = None  # Parsed JSON body (if Content-Type is application/json)
    error: Optional[str] = None      # Set when the HTTP call itself failed


@dataclass
class TestCorrelation:
    """Correlation configuration for test expectation."""
    message_id: Optional[str] = None
    source: Optional[Dict[str, str]] = None
    target: Optional[Dict[str, str]] = None


@dataclass
class TestInjection:
    """A message to inject during test setup (when phase)."""
    message_id: str
    destination: str           # Kafka topic, JMS queue, or HTTP URL (formerly 'topic')
    payload: Optional[str] = None
    payload_file: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    key: Optional[str] = None
    delay_ms: int = 0
    correlation_id: Optional[str] = None
    fault: Optional[Fault] = None
    msg_type: str = "kafka"            # YAML key: 'type'. Values: kafka | jms | http
    connection_ref: Optional[str] = None  # JMS queue manager ref (formerly queue_manager_ref)
    # HTTP-specific fields
    method: str = "POST"
    query_params: Optional[Dict[str, str]] = None
    auth_ref: Optional[str] = None     # Auth profile name (overrides host-match)
    tls_ref: Optional[str] = None      # TLS profile name (overrides host-match)
    http_timeout_ms: int = 10000

    # Backward compatibility aliases
    @property
    def topic(self) -> str:
        return self.destination

    @property
    def queue_manager_ref(self) -> Optional[str]:
        return self.connection_ref


@dataclass
class TestScript:
    """A script to execute (can be in when or then phase)."""
    script: str
    script_file: Optional[str] = None


@dataclass
class HttpStubResponse:
    """HTTP response definition for a type=http-stub expectation."""
    status_code: int = 200
    payload: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    content_type: str = "application/json"


@dataclass
class TestExpectation:
    """An expected message to receive during test validation (then phase)."""
    destination: str = ""              # Kafka topic, JMS queue (formerly 'topic'). Empty for type=http/http-stub
    wait_ms: int = 2000
    match: List[Condition] = field(default_factory=list)
    match_file: Optional[str] = None
    correlate: Optional[TestCorrelation] = None
    msg_type: str = "kafka"            # YAML key: 'type'. Values: kafka | jms | http | http-stub
    connection_ref: Optional[str] = None  # JMS queue manager ref (formerly queue_manager_ref)
    source_id: Optional[str] = None    # For type=http: references the message_id of the HTTP injection
    # Optional name for this expectation result.  When set, the first matched
    # message's payload fields are exposed as {{expect.<message_id>.<field>}}
    # template placeholders in subsequent then-phase items.
    message_id: Optional[str] = None

    # HTTP stub fields (type=http-stub only)
    server: Optional[str] = None       # Mock server name (from http-config/mock-servers/)
    path: Optional[str] = None         # URL path pattern, e.g. "/orders/{orderId}"
    method: str = "*"                  # HTTP method filter ("*" = any)
    response: Optional[HttpStubResponse] = None  # Response to return when stub is called
    times: int = 1                     # Expected number of calls

    # Backward compatibility aliases
    @property
    def topic(self) -> str:
        return self.destination

    @property
    def queue_manager_ref(self) -> Optional[str]:
        return self.connection_ref


@dataclass
class TestWhen:
    """Input phase of test: flat list of injections, DB actions, and scripts."""
    items: List[Union[TestInjection, TestScript, 'TestDBAction']] = field(default_factory=list)


@dataclass
class TestThen:
    """Output phase of test: flat list of expectations, DB actions, and scripts."""
    items: List[Union[TestExpectation, TestScript, 'TestDBAction']]


@dataclass
class TestDefinition:
    """A complete test definition."""
    name: str
    when: TestWhen
    then: TestThen
    priority: int = 999
    tags: List[str] = field(default_factory=list)
    skip: bool = False
    timeout_ms: int = 5000
    file_path: Optional[str] = None


class TestYamlParser:
    """Parses test YAML files."""

    @staticmethod
    def parse_test_yaml(yaml_content: str, file_path: str = "unknown") -> Dict[str, Any]:
        """
        Parse test YAML content.

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
                raise ValueError(f"Test YAML must be a dictionary at root level, got {type(data)}")
            return data
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {file_path}: {e}")

    @staticmethod
    def _parse_fault(fault_dict: Optional[Dict[str, Any]]) -> Optional[Fault]:
        """Parse optional fault injection configuration."""
        if not fault_dict:
            return None
        return Fault(
            drop=float(fault_dict.get('drop', 0.0)),
            duplicate=float(fault_dict.get('duplicate', 0.0)),
            random_latency=fault_dict.get('random_latency'),
            poison_pill=float(fault_dict.get('poison_pill', 0.0)),
            poison_pill_type=fault_dict.get('poison_pill_type', ['truncate']),
            check_result=bool(fault_dict.get('check_result', False))
        )


class TestValidator:
    """Validates test definitions."""

    @staticmethod
    def _parse_stub_response(response_dict: Optional[Dict[str, Any]]) -> Optional['HttpStubResponse']:
        """Parse optional HTTP stub response configuration."""
        if not response_dict:
            return None
        return HttpStubResponse(
            status_code=int(response_dict.get('status_code', 200)),
            payload=response_dict.get('payload'),
            headers=response_dict.get('headers') or {},
            content_type=response_dict.get('content_type', 'application/json'),
        )

    @staticmethod
    def validate_test_definition(test_dict: Dict[str, Any], file_path: str = "unknown") -> "TestDefinition":
        """
        Validate and convert test dictionary to TestDefinition.

        Args:
            test_dict: Parsed YAML dictionary
            file_path: Path to YAML file (for error reporting)

        Returns:
            TestDefinition object

        Raises:
            ValueError: If validation fails
        """
        try:
            # Validate required fields
            if "name" not in test_dict:
                raise ValueError("Missing required field: 'name'")
            if "when" not in test_dict:
                raise ValueError("Missing required field: 'when'")
            if "then" not in test_dict:
                raise ValueError("Missing required field: 'then'")

            name = str(test_dict["name"])
            priority = int(test_dict.get("priority", 999))
            tags = test_dict.get("tags", [])
            skip = bool(test_dict.get("skip", False))
            timeout_ms = int(test_dict.get("timeout_ms", 5000))

            if not isinstance(tags, list):
                tags = [tags] if tags else []

            # Parse when phase
            when_dict = test_dict.get("when", {})
            when = TestValidator._parse_when(when_dict)

            # Parse then phase
            then_dict = test_dict.get("then", {})
            then = TestValidator._parse_then(then_dict)

            logger.debug(f"Creating TestDefinition for {name} with file_path={file_path}")

            return TestDefinition(
                name=name,
                when=when,
                then=then,
                priority=priority,
                tags=tags,
                skip=skip,
                timeout_ms=timeout_ms,
                file_path=file_path
            )

        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"Invalid test definition in {file_path}: {e}")

    @staticmethod
    def _parse_when(when_dict: Dict[str, Any]) -> "TestWhen":
        """Parse 'when' phase - flat list of injections and scripts."""
        if "inject" not in when_dict:
            raise ValueError("'when' block must contain 'inject' list")

        inject_list = when_dict.get("inject", [])
        if not isinstance(inject_list, list):
            raise ValueError("'when.inject' must be a list")

        items = []
        for idx, item_dict in enumerate(inject_list):
            if not isinstance(item_dict, dict):
                raise ValueError(f"When item at index {idx} must be a dictionary")

            # Check if it's a script (inline or file-based)
            if "script" in item_dict and len(item_dict) == 1:
                # It's an inline script
                items.append(TestScript(script=str(item_dict["script"])))
            elif "script_file" in item_dict and len(item_dict) == 1:
                # It's a script file reference
                items.append(TestScript(script="", script_file=str(item_dict["script_file"])))
            elif str(item_dict.get("type", "kafka")).lower() == "db":
                # It's a DB action
                if "db" not in item_dict:
                    raise ValueError(f"DB action at index {idx} missing 'db' (database reference)")
                if "query" not in item_dict:
                    raise ValueError(f"DB action at index {idx} missing 'query'")
                op = str(item_dict.get("operation", "insert")).lower()
                step_id = item_dict.get("id", f"db_when_{idx}")
                items.append(TestDBAction(
                    id=step_id,
                    db_ref=str(item_dict["db"]),
                    operation=op,
                    query=str(item_dict["query"]),
                    params=item_dict.get("params"),
                    delay_ms=int(item_dict.get("delay_ms", 0)),
                ))
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

        return TestWhen(items=items)

    @staticmethod
    def _parse_then(then_dict: Dict[str, Any]) -> "TestThen":
        """Parse 'then' phase - flat list of expectations and scripts."""
        if "expectations" not in then_dict:
            raise ValueError("'then' block must contain 'expectations' list")

        expectations_list = then_dict.get("expectations", [])
        if not isinstance(expectations_list, list):
            raise ValueError("'then.expectations' must be a list")

        items = []
        for idx, item_dict in enumerate(expectations_list):
            if not isinstance(item_dict, dict):
                raise ValueError(f"Then item at index {idx} must be a dictionary")

            # Check if it's a script (inline or file-based)
            if "script" in item_dict and len(item_dict) == 1:
                # It's an inline script
                items.append(TestScript(script=str(item_dict["script"])))
            elif "script_file" in item_dict and len(item_dict) == 1:
                # It's a script file reference
                items.append(TestScript(script="", script_file=str(item_dict["script_file"])))
            elif str(item_dict.get("type", "kafka")).lower() == "db":
                # It's a DB action (cleanup, assertion, etc.)
                if "db" not in item_dict:
                    raise ValueError(f"DB action at index {idx} (then) missing 'db' field")
                if "query" not in item_dict:
                    raise ValueError(f"DB action at index {idx} (then) missing 'query' field")
                op = str(item_dict.get("operation", "select")).lower()
                step_id = item_dict.get("id", f"db_then_{idx}")

                # Parse optional match conditions (for DB assertions on select results)
                match_list = item_dict.get("match", [])
                conditions = []
                if isinstance(match_list, list):
                    for match_dict in match_list:
                        if not isinstance(match_dict, dict):
                            raise ValueError("DB match condition must be a dictionary")
                        ctype = match_dict.get("type")
                        if not ctype:
                            raise ValueError("DB match condition must have 'type' field")
                        conditions.append(Condition(
                            type=str(ctype),
                            expression=match_dict.get("expression"),
                            value=match_dict.get("value"),
                            regex=match_dict.get("regex"),
                        ))

                items.append(TestDBAction(
                    id=step_id,
                    db_ref=str(item_dict["db"]),
                    operation=op,
                    query=str(item_dict["query"]),
                    params=item_dict.get("params"),
                    delay_ms=int(item_dict.get("delay_ms", 0)),
                    match=conditions,
                    expected_row_count=item_dict.get("expected_row_count"),
                ))
            else:
                msg_type = str(item_dict.get("type", "kafka")).lower()
                # For http/http-stub expectations, destination is optional
                # (http: responses linked by source_id; http-stub: server+path used instead)
                if msg_type not in ("http", "http-stub") and "destination" not in item_dict:
                    raise ValueError(f"Expectation at index {idx} missing 'destination'")

                # Parse match conditions
                match_list = item_dict.get("match", [])
                conditions = []
                if isinstance(match_list, list):
                    for match_dict in match_list:
                        if not isinstance(match_dict, dict):
                            raise ValueError("Match condition must be a dictionary")

                        condition_type = match_dict.get("type")
                        if not condition_type:
                            raise ValueError("Match condition must have 'type' field")

                        condition = Condition(
                            type=str(condition_type),
                            expression=match_dict.get("expression"),
                            value=match_dict.get("value"),
                            regex=match_dict.get("regex")
                        )
                        conditions.append(condition)

                # Parse correlation configuration
                correlate = None
                if "correlate" in item_dict:
                    corr_dict = item_dict["correlate"]
                    correlate = TestCorrelation(
                        message_id=corr_dict.get("message_id"),
                        source=corr_dict.get("source"),
                        target=corr_dict.get("target")
                    )

                expectation = TestExpectation(
                    destination=str(item_dict.get("destination", "")),
                    wait_ms=int(item_dict.get("wait_ms", 2000)),
                    match=conditions,
                    match_file=item_dict.get("match_file"),
                    correlate=correlate,
                    msg_type=msg_type,
                    connection_ref=item_dict.get("connection_ref"),
                    source_id=item_dict.get("source_id"),
                    message_id=item_dict.get("message_id"),
                    # HTTP stub fields (type=http-stub)
                    server=item_dict.get("server"),
                    path=item_dict.get("path"),
                    method=str(item_dict.get("method", "*")).upper() if item_dict.get("method") else "*",
                    times=int(item_dict.get("times", 1)),
                    response=TestValidator._parse_stub_response(item_dict.get("response")),
                )
                items.append(expectation)

        return TestThen(items=items)


class TestLoader:
    """Loads and discovers test definitions from /testSuite/ directory."""

    def __init__(self, test_suite_dir: str = "/testSuite"):
        """
        Initialize test loader.

        Args:
            test_suite_dir: Path to testSuite directory
        """
        self.test_suite_dir = Path(test_suite_dir)
        self.test_suite_dir.mkdir(parents=True, exist_ok=True)
        # Track validation errors per file
        self.validation_errors: Dict[str, List[str]] = {}
        # Cache for test discovery
        self._cached_tests: Optional[List[TestDefinition]] = None
        self._cached_test_files: Optional[Set[str]] = None

    def discover_tests(self) -> List[TestDefinition]:
        """
        Discover and load all test files from /testSuite/ directory.
        Uses caching to avoid repeated logging when test files haven't changed.

        Returns:
            List of TestDefinition objects, sorted by priority
        """
        # Build {path: mtime} dict — detects both new/removed files AND edits
        yaml_files = sorted(self.test_suite_dir.rglob("*.test.yaml")) + \
                     sorted(self.test_suite_dir.rglob("*.test.yml"))
        current_files = {str(f): f.stat().st_mtime for f in yaml_files}

        # Cache hit: same files AND none of them were modified
        if self._cached_tests is not None and self._cached_test_files == current_files:
            return self._cached_tests

        # Tests have changed, reload them
        tests = []

        if not yaml_files:
            logger.debug(f"No test files found in {self.test_suite_dir}")
            self._cached_tests = tests
            self._cached_test_files = current_files
            return tests

        for yaml_file in yaml_files:
            try:
                test = self.load_test_file(yaml_file)
                tests.append(test)
                logger.info(f"Loaded test: {test.name} from {yaml_file}")
                logger.debug(f"  Test file_path: {test.file_path}")
            except Exception as e:
                logger.error(f"Failed to load test {yaml_file.name}: {e}")

        # Sort by priority (lower = first) then by name
        tests.sort(key=lambda t: (t.priority, t.name))
        logger.info(f"Discovered {len(tests)} tests")

        # Cache the results
        self._cached_tests = tests
        self._cached_test_files = current_files
        return tests

    def load_test_file(self, file_path: Path) -> TestDefinition:
        """
        Load a single test file.

        Args:
            file_path: Path to test YAML file

        Returns:
            TestDefinition object

        Raises:
            ValueError: If file is invalid
        """
        try:
            with open(file_path, "r") as f:
                yaml_content = f.read()

            test_dict = TestYamlParser.parse_test_yaml(yaml_content, str(file_path))
            test = TestValidator.validate_test_definition(test_dict, str(file_path))

            test_dir = Path(file_path).parent
            self._resolve_payload_files(test, test_dir)
            self._resolve_script_files(test, test_dir)

            return test
        except Exception as e:
            raise ValueError(f"Failed to load test from {file_path}: {e}")

    def _resolve_payload_files(self, test: TestDefinition, test_dir: Path):
        """
        Resolve external payload files in test definition.

        Args:
            test: Test definition to resolve
            test_dir: Directory where test file is located
        """
        # Resolve payloads in when phase
        for item in test.when.items:
            if isinstance(item, TestInjection) and item.payload_file:
                payload_path = test_dir / item.payload_file
                if not payload_path.exists():
                    logger.warning(f"Payload file not found: {payload_path}")
                else:
                    try:
                        with open(payload_path, "r") as f:
                            item.payload = f.read()
                        logger.debug(f"Loaded payload from {item.payload_file}")
                    except Exception as e:
                        logger.error(f"Failed to load payload file {item.payload_file}: {e}")

        # Resolve match files in then phase
        for item in test.then.items:
            if isinstance(item, TestExpectation) and item.match_file:
                match_path = test_dir / item.match_file
                if not match_path.exists():
                    logger.warning(f"Match file not found: {match_path}")
                else:
                    try:
                        with open(match_path, "r") as f:
                            import yaml as _yaml
                            match_data = _yaml.safe_load(f)
                            if isinstance(match_data, list):
                                # Each item in match file is a condition
                                for match_dict in match_data:
                                    if isinstance(match_dict, dict):
                                        condition = Condition(
                                            type=str(match_dict.get("type", "")),
                                            expression=match_dict.get("expression"),
                                            value=match_dict.get("value"),
                                            regex=match_dict.get("regex")
                                        )
                                        item.match.append(condition)
                        logger.debug(f"Loaded match conditions from {item.match_file}")
                    except Exception as e:
                        logger.error(f"Failed to load match file {item.match_file}: {e}")

    def _resolve_script_files(self, test: TestDefinition, test_dir: Path):
        """
        Resolve external script files in test definition.

        Args:
            test: Test definition to resolve
            test_dir: Directory where test file is located
        """
        # Resolve scripts in when phase
        for item in test.when.items:
            if isinstance(item, TestScript) and item.script_file:
                script_path = test_dir / item.script_file
                if not script_path.exists():
                    logger.warning(f"Script file not found: {script_path}")
                else:
                    try:
                        with open(script_path, "r") as f:
                            item.script = f.read()
                        logger.debug(f"Loaded script from {item.script_file}")
                    except Exception as e:
                        logger.error(f"Failed to load script file {item.script_file}: {e}")

        # Resolve scripts in then phase
        for item in test.then.items:
            if isinstance(item, TestScript) and item.script_file:
                script_path = test_dir / item.script_file
                if not script_path.exists():
                    logger.warning(f"Script file not found: {script_path}")
                else:
                    try:
                        with open(script_path, "r") as f:
                            item.script = f.read()
                        logger.debug(f"Loaded script from {item.script_file}")
                    except Exception as e:
                        logger.error(f"Failed to load script file {item.script_file}: {e}")

    def discover_then_topics(self, tests: List[TestDefinition]) -> Set[str]:
        """
        Extract all output topics from test expectations (then phase).

        Args:
            tests: List of test definitions

        Returns:
            Set of topic names
        """
        topics = set()
        for test in tests:
            for item in test.then.items:
                if isinstance(item, TestExpectation) and item.msg_type != "http":
                    topics.add(item.destination)
        return topics

    def get_tests_by_tag(self, tests: List[TestDefinition], tags: List[str]) -> List[TestDefinition]:
        """
        Filter tests by tags (returns tests matching ANY of the provided tags).

        Args:
            tests: List of test definitions
            tags: List of tag names to filter by

        Returns:
            Filtered list of tests
        """
        if not tags:
            return tests
        return [test for test in tests if any(tag in test.tags for tag in tags)]
