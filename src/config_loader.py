"""
Configuration loader with hot-reload support.
"""
import os
import yaml
import logging
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import threading
logger = logging.getLogger(__name__)
@dataclass
class Condition:
    """A matching condition."""
    type: str  # jsonpath, exact, partial, regex
    expression: Optional[str] = None  # for jsonpath
    value: Optional[Any] = None  # expected value
    regex: Optional[str] = None  # regex pattern
@dataclass
class Output:
    """Output message to a topic."""
    topic: str
    payload: str
    delay_ms: int = 0
    headers: Optional[Dict[str, str]] = None
    schema_id: Optional[int] = None  # AVRO schema ID

    @property
    def message_template(self):
        """Backward compatibility property"""
        return self.payload

@dataclass
class Rule:
    """A matching rule with when/then structure."""
    priority: int
    input_topic: str
    conditions: List[Condition]  # All must match (AND logic)
    outputs: List[Output]
    rule_name: str = ""
class ConfigLoader:
    """Loads and hot-reloads configuration from YAML files."""
    def __init__(self, config_dir: str = "/config", reload_interval: int = 30):
        """
        Initialize the config loader.
        Args:
            config_dir: Directory to scan for YAML files
            reload_interval: Interval in seconds to check for config changes
        """
        self.config_dir = Path(config_dir)
        self.reload_interval = reload_interval
        self.rules: List[Rule] = []
        self.rules_by_input_topic: Dict[str, List[Rule]] = {}
        self._file_hashes: Dict[Path, str] = {}  # Track file hashes instead of timestamps
        self._lock = threading.Lock()
        self._last_reload = datetime.now()
        # Create config directory if it doesn't exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Load initial config
        self.reload()
    def get_rules_for_topic(self, input_topic: str) -> List[Rule]:
        """Get all rules that apply to a given input topic, sorted by priority."""
        with self._lock:
            rules = self.rules_by_input_topic.get(input_topic, [])
            # Return sorted by priority (lower number = higher priority)
            return sorted(rules, key=lambda r: (r.priority, r.rule_name))
    def get_all_rules(self) -> List[Rule]:
        """Get all rules sorted by priority."""
        with self._lock:
            return sorted(self.rules, key=lambda r: (r.priority, r.rule_name))
    def check_and_reload(self) -> bool:
        """
        Check if any config files have changed and reload if needed.
        Returns:
            True if reload occurred, False otherwise
        """
        now = datetime.now()
        if now - self._last_reload < timedelta(seconds=self.reload_interval):
            return False
        # Check if any files have been modified
        if self._check_files_changed():
            logger.info("Config files changed, reloading...")
            self.reload()
            self._last_reload = now
            return True
        self._last_reload = now
        return False
    def _check_files_changed(self) -> bool:
        """Check if any YAML files have been modified by comparing hashes."""
        yaml_files = list(self.config_dir.rglob("*.yaml")) + list(self.config_dir.rglob("*.yml"))
        current_files = set(yaml_files)
        tracked_files = set(self._file_hashes.keys())

        # Check for removed files
        removed_files = tracked_files - current_files
        if removed_files:
            logger.info(f"Config files removed: {[f.name for f in removed_files]}")
            # Remove from tracking and clear the tracking dict to update cache
            for removed_file in removed_files:
                del self._file_hashes[removed_file]
            return True

        # Check for new files
        new_files = current_files - tracked_files
        if new_files:
            logger.info(f"Config files added: {[f.name for f in new_files]}")
            return True

        # Check for modified files by comparing content hashes
        for yaml_file in yaml_files:
            try:
                current_hash = self._calculate_file_hash(yaml_file)
                last_hash = self._file_hashes.get(yaml_file)
                if last_hash is None or current_hash != last_hash:
                    logger.info(f"Config file changed: {yaml_file.name}")
                    # Update hash so we don't detect this as changed on next check
                    self._file_hashes[yaml_file] = current_hash
                    return True
            except OSError as e:
                logger.warning(f"Cannot read file {yaml_file}: {e}")
                return True

        return False

    @staticmethod
    def _calculate_file_hash(file_path: Path) -> str:
        """Calculate SHA256 hash of file content."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    def reload(self) -> None:
        """Load all YAML configuration files."""
        logger.info(f"Loading configuration from {self.config_dir}")
        new_rules = []
        new_file_hashes = {}
        yaml_files = sorted(self.config_dir.rglob("*.yaml")) + sorted(self.config_dir.rglob("*.yml"))
        if not yaml_files:
            logger.warning(f"No YAML configuration files found in {self.config_dir}")
        for yaml_file in yaml_files:
            try:
                rules = self._load_yaml_file(yaml_file)
                new_rules.extend(rules)
                logger.info(f"Loaded {yaml_file.name}")
                # Track the hash for this file
                new_file_hashes[yaml_file] = self._calculate_file_hash(yaml_file)
            except Exception as e:
                logger.error(f"Failed to load {yaml_file}: {e}")
        # Sort by priority and filename
        new_rules.sort(key=lambda r: (r.priority, r.rule_name))
        with self._lock:
            self.rules = new_rules
            self._file_hashes = new_file_hashes  # Replace entire hash tracking
            self._rebuild_topic_index()
        logger.info(f"Loaded total of {len(new_rules)} rules")
    def _rebuild_topic_index(self) -> None:
        """Rebuild the index of rules by input topic."""
        self.rules_by_input_topic.clear()
        for rule in self.rules:
            if rule.input_topic not in self.rules_by_input_topic:
                self.rules_by_input_topic[rule.input_topic] = []
            self.rules_by_input_topic[rule.input_topic].append(rule)
    def _load_yaml_file(self, yaml_file: Path) -> List[Rule]:
        """Load rules from a single YAML file."""
        with open(yaml_file, 'r') as f:
            data = yaml.safe_load(f)
        if not data:
            logger.warning(f"Empty YAML file: {yaml_file}")
            return []
        rules = []
        # Check if this is a single rule file (new format) or multi-rule file (old format)
        if 'when' in data or 'priority' in data:
            # Single rule per file (new format)
            try:
                rule = self._parse_rule_new_format(data, yaml_file.name)
                rules.append(rule)
            except Exception as e:
                logger.error(f"Failed to parse rule in {yaml_file}: {e}")
        elif 'rules' in data:
            # Multiple rules per file (old format)
            for i, rule_data in enumerate(data['rules']):
                try:
                    rule = self._parse_rule_old_format(rule_data, yaml_file.name, i)
                    rules.append(rule)
                except Exception as e:
                    logger.error(f"Failed to parse rule {i} in {yaml_file}: {e}")
        else:
            logger.warning(f"No 'when' or 'rules' key found in {yaml_file}")
        return rules
    def _parse_rule_new_format(self, rule_data: Dict[str, Any], filename: str) -> Rule:
        """Parse a rule in the new format (when/then)."""
        # Priority is required
        priority = rule_data.get('priority')
        if priority is None:
            raise ValueError("Priority is required")
        # Get rule name
        rule_name = rule_data.get('name') or filename.replace('.yaml', '').replace('.yml', '')
        # Parse 'when' block
        when_block = rule_data.get('when')
        if not when_block:
            raise ValueError("'when' block is required")
        input_topic = when_block.get('topic')
        if not input_topic:
            raise ValueError("Topic is required in 'when' block")
        # Parse match conditions (all optional conditions are ANDed)
        conditions = []
        match_list = when_block.get('match', [])
        if match_list:
            if not isinstance(match_list, list):
                match_list = [match_list]
            for match_item in match_list:
                condition_type = match_item.get('type', 'jsonpath').lower()

                if condition_type == 'jsonpath':
                    condition = Condition(
                        type='jsonpath',
                        expression=match_item.get('expression'),
                        value=match_item.get('value'),
                        regex=match_item.get('regex')
                    )
                elif condition_type == 'exact':
                    condition = Condition(
                        type='exact',
                        value=match_item.get('value'),
                        expression=None,
                        regex=None
                    )
                elif condition_type == 'partial':
                    condition = Condition(
                        type='partial',
                        value=match_item.get('value'),
                        expression=None,
                        regex=None
                    )
                elif condition_type == 'regex':
                    condition = Condition(
                        type='regex',
                        regex=match_item.get('regex'),
                        value=None,
                        expression=None
                    )
                else:
                    raise ValueError(f"Unknown match type: {condition_type}. Supported: jsonpath, exact, partial, regex")

                conditions.append(condition)
        # Parse 'then' block (output messages)
        then_block = rule_data.get('then', [])
        if not isinstance(then_block, list):
            then_block = [then_block]
        if not then_block:
            raise ValueError("'then' block must contain at least one output")
        outputs = []
        for then_item in then_block:
            output_topic = then_item.get('topic')
            if not output_topic:
                raise ValueError("Topic is required in output")
            output = Output(
                topic=output_topic,
                payload=then_item.get('payload', ''),
                delay_ms=then_item.get('delay_ms', 0),
                headers=then_item.get('headers'),
                schema_id=then_item.get('schema_id')  # AVRO schema ID
            )
            outputs.append(output)
        return Rule(
            priority=priority,
            input_topic=input_topic,
            conditions=conditions,
            outputs=outputs,
            rule_name=rule_name,
        )
    def _parse_rule_old_format(self, rule_data: Dict[str, Any], filename: str, index: int) -> Rule:
        """Parse a rule in the old format (for backward compatibility)."""
        # Validate required fields
        required = ['match_strategy', 'match_condition', 'input_topic', 'outputs']
        for field in required:
            if field not in rule_data:
                raise ValueError(f"Missing required field: {field}")
        priority = rule_data.get('priority', 100)
        rule_name = rule_data.get('name', f"{filename}#{index}")
        input_topic = rule_data['input_topic']
        # Convert old format to new format
        conditions = []
        match_strategy = rule_data['match_strategy']
        match_condition = rule_data['match_condition']
        # For backward compatibility, treat old format as jsonpath or exact
        if match_strategy.lower() == 'jsonpath' and isinstance(match_condition, dict):
            condition = Condition(
                type='jsonpath',
                expression=match_condition.get('path'),
                value=match_condition.get('value')
            )
        else:
            # Convert other strategies to jsonpath with expression matching
            condition = Condition(
                type='jsonpath',
                value=match_condition
            )
        conditions.append(condition)
        # Parse outputs
        outputs_data = rule_data['outputs']
        if not isinstance(outputs_data, list):
            outputs_data = [outputs_data]
        outputs = []
        for output_data in outputs_data:
            if isinstance(output_data, dict):
                topic = output_data.get('topic')
                payload = output_data.get('message_template', "")
            else:
                topic = str(output_data)
                payload = ""
            if not topic:
                raise ValueError("Output must have a 'topic' field")
            outputs.append(Output(topic=topic, payload=payload))
        return Rule(
            priority=priority,
            input_topic=input_topic,
            conditions=conditions,
            outputs=outputs,
            rule_name=rule_name,
        )
