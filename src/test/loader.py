"""
Test Suite YAML loader and validator.
Parses test definitions from YAML files in /testSuite/ directory.
"""
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Union
from dataclasses import dataclass, field
from src.config.models import Condition

logger = logging.getLogger(__name__)


@dataclass
class TestInjection:
    """A message to inject during test setup (when phase)."""
    message_id: str
    topic: str
    payload: Optional[str] = None  # String (will be templated)
    payload_file: Optional[str] = None  # Path to external payload file (relative to test file)
    headers: Optional[Dict[str, str]] = None
    delay_ms: int = 0


@dataclass
class TestScript:
    """A script to execute (can be in when or then phase)."""
    script: str  # Python code
    script_file: Optional[str] = None  # Path to external script file (relative to test file)


@dataclass
class TestExpectation:
    """An expected message to receive during test validation (then phase)."""
    topic: str
    message_id: Optional[str] = None  # Which injected message to correlate with
    source_id: Optional[str] = None  # Field in that message (e.g. "$.orderId")
    target_id: Optional[str] = None  # Field in received message to match against
    wait_ms: int = 2000  # Default 2s timeout
    match: List[Condition] = field(default_factory=list)  # Optional conditions
    match_file: Optional[str] = None  # Path to external match conditions file (YAML)


@dataclass
class TestWhen:
    """Input phase of test: flat list of injections and scripts."""
    items: List[Union[TestInjection, TestScript]] = field(default_factory=list)  # Mixed items, executed sequentially


@dataclass
class TestThen:
    """Output phase of test: flat list of expectations and scripts."""
    items: List[Union[TestExpectation, TestScript]]  # Mixed items, executed sequentially


@dataclass
class TestDefinition:
    """A complete test definition."""
    name: str  # Test identifier
    when: TestWhen
    then: TestThen
    priority: int = 999  # Optional; lower = runs first
    tags: List[str] = field(default_factory=list)  # Optional; for filtering
    skip: bool = False  # Optional; default false
    timeout_ms: int = 5000  # Optional; overall test timeout
    file_path: Optional[str] = None  # Path to the test YAML file (for logging)


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


class TestValidator:
    """Validates test definitions."""

    @staticmethod
    def validate_test_definition(test_dict: Dict[str, Any], file_path: str = "unknown") -> TestDefinition:
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
    def _parse_when(when_dict: Dict[str, Any]) -> TestWhen:
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
            else:
                # It's an injection
                if "message_id" not in item_dict:
                    raise ValueError(f"Injection at index {idx} missing 'message_id'")
                if "topic" not in item_dict:
                    raise ValueError(f"Injection at index {idx} missing 'topic'")
                if "payload" not in item_dict and "payload_file" not in item_dict:
                    raise ValueError(f"Injection at index {idx} missing 'payload' or 'payload_file'")

                injection = TestInjection(
                    message_id=str(item_dict["message_id"]),
                    topic=str(item_dict["topic"]),
                    payload=str(item_dict["payload"]) if "payload" in item_dict else None,
                    payload_file=item_dict.get("payload_file"),
                    headers=item_dict.get("headers"),
                    delay_ms=int(item_dict.get("delay_ms", 0))
                )
                items.append(injection)

        return TestWhen(items=items)

    @staticmethod
    def _parse_then(then_dict: Dict[str, Any]) -> TestThen:
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
            else:
                # It's an expectation
                if "topic" not in item_dict:
                    raise ValueError(f"Expectation at index {idx} missing 'topic'")

                # Parse match conditions
                match_list = item_dict.get("match", [])
                conditions = []
                if isinstance(match_list, list):
                    for match_dict in match_list:
                        if not isinstance(match_dict, dict):
                            raise ValueError(f"Match condition must be a dictionary")

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

                expectation = TestExpectation(
                    topic=str(item_dict["topic"]),
                    message_id=item_dict.get("message_id"),
                    source_id=item_dict.get("source_id"),
                    target_id=item_dict.get("target_id"),
                    wait_ms=int(item_dict.get("wait_ms", 2000)),
                    match=conditions,
                    match_file=item_dict.get("match_file")
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

    def discover_tests(self) -> List[TestDefinition]:
        """
        Discover and load all test files from /testSuite/ directory.

        Returns:
            List of TestDefinition objects, sorted by priority
        """
        tests = []
        yaml_files = sorted(self.test_suite_dir.rglob("*.test.yaml")) + \
                     sorted(self.test_suite_dir.rglob("*.test.yml"))

        if not yaml_files:
            logger.debug(f"No test files found in {self.test_suite_dir}")
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
            
            # Resolve payload files and script files relative to test file directory
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
                            import yaml
                            match_data = yaml.safe_load(f)
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
                if isinstance(item, TestExpectation):
                    topics.add(item.topic)
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

