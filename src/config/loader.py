"""Configuration loader with hot-reload support."""
import yaml
import logging
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import threading

from .models import Condition, Output, Rule, CorrelationInput, CorrelationOutput, Fault
from .topic_config import TopicConfigLoader

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads and hot-reloads configuration from YAML files."""

    def __init__(self, config_dir: str = "/config", reload_interval: int = 30,
                 schema_registry_url: Optional[str] = None):
        """Initialize the config loader."""
        self.config_dir = Path(config_dir)
        self.reload_interval = reload_interval
        self.rules: List[Rule] = []
        self.rules_by_input_topic: Dict[str, List[Rule]] = {}
        self._file_hashes: Dict[Path, str] = {}
        self._lock = threading.Lock()
        self._last_reload = datetime.now()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Track validation errors per file
        self.validation_errors: Dict[str, List[str]] = {}

        # Initialize topic config loader
        self.topic_config_loader = TopicConfigLoader(
            config_dir=config_dir,
            scan_interval=reload_interval,
            global_schema_registry_url=schema_registry_url
        )
        self.topic_config_loader.start()

        self.reload()

    def get_rules_for_topic(self, input_topic: str) -> List[Rule]:
        """Get all rules that apply to a given input topic, sorted by priority."""
        with self._lock:
            rules = self.rules_by_input_topic.get(input_topic, [])
            return sorted(rules, key=lambda r: (r.priority, r.rule_name))

    def get_all_rules(self) -> List[Rule]:
        """Get all rules sorted by priority."""
        with self._lock:
            return sorted(self.rules, key=lambda r: (r.priority, r.rule_name))

    def check_and_reload(self) -> bool:
        """Check if any config files have changed and reload if needed."""
        now = datetime.now()
        if now - self._last_reload < timedelta(seconds=self.reload_interval):
            return False
        if self._check_files_changed():
            logger.info("Config files changed, reloading...")
            self.reload()
            self._last_reload = now
            return True
        self._last_reload = now
        return False

    def _check_files_changed(self) -> bool:
        """Check if any YAML files have been modified by comparing hashes."""
        # Get all YAML files, but exclude topic-config and custom-placeholders directories
        yaml_files = []
        for yaml_file in list(self.config_dir.rglob("*.yaml")) + list(self.config_dir.rglob("*.yml")):
            # Skip directories handled by their own specialised loaders
            if any(d in yaml_file.parts for d in ("topic-config", "custom_placeholders", "http-config", "jms-config", "db-config")):
                continue
            yaml_files.append(yaml_file)
        
        current_files = set(yaml_files)
        tracked_files = set(self._file_hashes.keys())

        removed_files = tracked_files - current_files
        if removed_files:
            logger.info(f"Config files removed: {[f.name for f in removed_files]}")
            for removed_file in removed_files:
                del self._file_hashes[removed_file]
            return True

        new_files = current_files - tracked_files
        if new_files:
            logger.info(f"Config files added: {[f.name for f in new_files]}")
            return True

        for yaml_file in yaml_files:
            try:
                current_hash = self._calculate_file_hash(yaml_file)
                last_hash = self._file_hashes.get(yaml_file)
                if last_hash is None or current_hash != last_hash:
                    logger.info(f"Config file changed: {yaml_file.name}")
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

        # Get all YAML files, but exclude topic-config and custom-placeholders directories
        # (they are handled by their own loaders)
        yaml_files = []
        for yaml_file in sorted(self.config_dir.rglob("*.yaml")) + sorted(self.config_dir.rglob("*.yml")):
            # Skip directories handled by their own specialised loaders
            if any(d in yaml_file.parts for d in ("topic-config", "custom_placeholders", "http-config", "jms-config", "db-config")):
                logger.debug(f"Skipping {yaml_file.name} (handled by specialized loader)")
                continue
            yaml_files.append(yaml_file)

        if not yaml_files:
            logger.warning(f"No YAML rule files found in {self.config_dir}")

        for yaml_file in yaml_files:
            try:
                rules = self._load_yaml_file(yaml_file)
                for rule in rules:
                    self._resolve_payload_files_in_rule(rule, yaml_file.parent)
                new_rules.extend(rules)
                logger.info(f"Loaded {yaml_file.name}")
                new_file_hashes[yaml_file] = self._calculate_file_hash(yaml_file)
            except Exception as e:
                logger.error(f"Failed to load {yaml_file}: {e}")
        new_rules.sort(key=lambda r: (r.priority, r.rule_name))
        with self._lock:
            self.rules = new_rules
            self._file_hashes = new_file_hashes
            self._rebuild_topic_index()
        logger.info(f"Loaded total of {len(new_rules)} rules")

    def _rebuild_topic_index(self) -> None:
        """Rebuild the index of rules by input destination."""
        self.rules_by_input_topic.clear()
        for rule in self.rules:
            if rule.input_destination not in self.rules_by_input_topic:
                self.rules_by_input_topic[rule.input_destination] = []
            self.rules_by_input_topic[rule.input_destination].append(rule)

    def _resolve_payload_files_in_rule(self, rule: Rule, rule_dir: Path):
        """Resolve external payload files in rule outputs."""
        for output in rule.outputs:
            if output.payload_file:
                payload_path = rule_dir / output.payload_file
                if not payload_path.exists():
                    logger.warning(f"Payload file not found for rule {rule.rule_name}: {payload_path}")
                else:
                    try:
                        with open(payload_path, "r") as f:
                            output.payload = f.read()
                        logger.debug(f"Loaded payload from {output.payload_file} for rule {rule.rule_name}")
                    except Exception as e:
                        logger.error(f"Failed to load payload file {output.payload_file}: {e}")

    def _load_yaml_file(self, yaml_file: Path) -> List[Rule]:
        """Load rules from a single YAML file."""
        with open(yaml_file, 'r') as f:
            data = yaml.safe_load(f)
        if not data:
            logger.warning(f"Empty YAML file: {yaml_file}")
            return []
        rules = []
        if 'when' in data or 'priority' in data:
            try:
                rule = self._parse_rule_new_format(data, yaml_file.name)
                rules.append(rule)
            except Exception as e:
                logger.error(f"Failed to parse rule in {yaml_file}: {e}")
        elif 'rules' in data:
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
        priority = rule_data.get('priority')
        if priority is None:
            raise ValueError("Priority is required")
        rule_name = rule_data.get('name') or filename.replace('.yaml', '').replace('.yml', '')
        skip = rule_data.get('skip', False)
        when_block = rule_data.get('when')
        if not when_block:
            raise ValueError("'when' block is required")
        input_destination = when_block.get('destination')
        if not input_destination:
            raise ValueError("'destination' is required in 'when' block")

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
                elif condition_type == 'header':
                    condition = Condition(
                        type='header',
                        expression=match_item.get('expression'),
                        value=match_item.get('value'),
                        regex=match_item.get('regex')
                    )
                elif condition_type == 'key':
                    condition = Condition(
                        type='key',
                        value=match_item.get('value'),
                        regex=match_item.get('regex'),
                        expression=None
                    )
                elif condition_type == 'path_param':
                    condition = Condition(
                        type='path_param',
                        expression=match_item.get('expression'),
                        value=match_item.get('value'),
                        regex=match_item.get('regex')
                    )
                elif condition_type == 'query_param':
                    condition = Condition(
                        type='query_param',
                        expression=match_item.get('expression'),
                        value=match_item.get('value'),
                        regex=match_item.get('regex')
                    )
                else:
                    raise ValueError(
                        f"Unknown match type: {condition_type}. "
                        f"Supported: jsonpath, exact, partial, regex, header, key, path_param, query_param"
                    )
                conditions.append(condition)

        then_block = rule_data.get('then', [])
        if not isinstance(then_block, list):
            then_block = [then_block]
        if not then_block:
            raise ValueError("'then' block must contain at least one output")

        outputs = []
        http_response_count = 0
        for then_item in then_block:
            output_msg_type = then_item.get('type', 'kafka').lower()
            output_destination = then_item.get('destination', '')

            # DB outputs: no destination/payload required
            if output_msg_type == 'db':
                if not then_item.get('db'):
                    raise ValueError("DB output requires 'db' field (database reference)")
                if not then_item.get('query'):
                    raise ValueError("DB output requires 'query' field")
                output = Output(
                    destination='',
                    msg_type='db',
                    delay_ms=then_item.get('delay_ms', 0),
                    db_ref=then_item.get('db'),
                    db_operation=str(then_item.get('operation', 'insert')).lower(),
                    db_query=then_item.get('query'),
                    db_params=then_item.get('params'),
                    db_step_id=then_item.get('id'),
                )
                outputs.append(output)
                continue

            # http_response outputs return data to the caller — no external destination needed
            if output_msg_type != 'http_response' and not output_destination:
                raise ValueError("'destination' is required in output")
            # Neither http nor http_response outputs require a payload body
            if output_msg_type not in ('http', 'http_response') and "payload" not in then_item and "payload_file" not in then_item:
                raise ValueError("'payload' or 'payload_file' is required in output")
            if output_msg_type == 'http_response':
                http_response_count += 1
                if http_response_count > 1:
                    raise ValueError("At most one 'http_response' output is allowed per rule")

            # Parse optional correlation for output
            correlation = None
            if "correlation" in then_item:
                corr_data = then_item["correlation"]
                correlation = CorrelationOutput(
                    to_headers=corr_data.get("to_headers")
                )

            # Parse optional fault injection for output
            fault = None
            if "fault" in then_item:
                fault_data = then_item["fault"]
                fault = Fault(
                    drop=float(fault_data.get('drop', 0.0)),
                    duplicate=float(fault_data.get('duplicate', 0.0)),
                    random_latency=fault_data.get('random_latency'),
                    poison_pill=float(fault_data.get('poison_pill', 0.0)),
                    poison_pill_type=fault_data.get('poison_pill_type', ['truncate']),
                    check_result=bool(fault_data.get('check_result', False))
                )

            output = Output(
                destination=output_destination,
                msg_type=output_msg_type,
                payload=then_item.get('payload'),
                payload_file=then_item.get('payload_file'),
                delay_ms=then_item.get('delay_ms', 0),
                headers=then_item.get('headers'),
                key=then_item.get('key'),
                schema_id=then_item.get('schema_id'),
                correlation=correlation,
                fault=fault,
                connection_ref=then_item.get('connection_ref'),
                method=then_item.get('method', 'POST'),
                query_params=then_item.get('query_params'),
                auth_ref=then_item.get('auth_ref'),
                tls_ref=then_item.get('tls_ref'),
                http_timeout_ms=int(then_item.get('http_timeout_ms', 10000)),
                status_code=int(then_item.get('status_code', 200)),
                response_content_type=then_item.get('response_content_type'),
            )
            outputs.append(output)

        # Parse optional correlation for input (when block)
        input_correlation = None
        if "correlation" in when_block:
            corr_data = when_block["correlation"]
            extract_rules = corr_data.get("extract", [])
            input_correlation = CorrelationInput(extract=extract_rules)

        # Parse input message type and method from when block
        input_type = when_block.get('type', 'kafka').lower()
        raw_method = when_block.get('method', '*')
        input_method = str(raw_method).upper() if raw_method and raw_method != '*' else '*'
        # connection_ref on when block: JMS queue manager name OR HTTP mock server name
        input_connection_ref = when_block.get('connection_ref')

        return Rule(
            priority=priority,
            input_destination=input_destination,
            conditions=conditions,
            outputs=outputs,
            rule_name=rule_name,
            correlation=input_correlation,
            skip=skip,
            input_type=input_type,
            input_method=input_method,
            connection_ref=input_connection_ref,
        )

    def _parse_rule_old_format(self, rule_data: Dict[str, Any], filename: str, index: int) -> Rule:
        """Parse a rule in the old format (for backward compatibility)."""
        required = ['match_strategy', 'match_condition', 'input_topic', 'outputs']
        for field in required:
            if field not in rule_data:
                raise ValueError(f"Missing required field: {field}")
        priority = rule_data.get('priority', 100)
        rule_name = rule_data.get('name', f"{filename}#{index}")
        input_destination = rule_data['input_topic']  # old format uses 'input_topic'

        conditions = []
        match_strategy = rule_data['match_strategy']
        match_condition = rule_data['match_condition']
        if match_strategy.lower() == 'jsonpath' and isinstance(match_condition, dict):
            condition = Condition(
                type='jsonpath',
                expression=match_condition.get('path'),
                value=match_condition.get('value')
            )
        else:
            condition = Condition(
                type='jsonpath',
                value=match_condition
            )
        conditions.append(condition)

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
            outputs.append(Output(destination=topic, payload=payload))

        return Rule(
            priority=priority,
            input_destination=input_destination,
            conditions=conditions,
            outputs=outputs,
            rule_name=rule_name,
        )

