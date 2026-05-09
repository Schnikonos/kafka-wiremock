"""
Send execution engine - simplified version for message injection only.
"""
import json
import logging
import asyncio
import time
from typing import Dict, List, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from .loader import SendDefinition
from ..kafka.client import KafkaClientWrapper
from ..rules.templater import TemplateRenderer
from ..custom.placeholders import CustomPlaceholderRegistry
from ..fault.injector import FaultInjector
from ..test.logger import TestLogger
from ..test.loader import TestInjection, TestScript

logger = logging.getLogger(__name__)


@dataclass
class InjectedMessage:
    """Captured injected message for context."""
    message_id: str
    topic: str
    payload: Any  # Parsed JSON or string
    headers: Optional[Dict[str, str]] = None
    timestamp: int = 0  # Milliseconds
    status: str = "ok"  # "ok" or error message


@dataclass
class SendResult:
    """Result of a send execution."""
    send_id: str
    status: str  # "COMPLETED", "FAILED", "SKIPPED"
    elapsed_ms: int = 0
    injected: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class SendExecutor:
    """Executes individual send definitions."""

    def __init__(
        self,
        kafka_client: KafkaClientWrapper,
        custom_placeholder_registry: Optional[CustomPlaceholderRegistry] = None,
        send_dir: str = "/send"
    ):
        """Initialize send executor."""
        self.kafka_client = kafka_client
        self.custom_placeholder_registry = custom_placeholder_registry or CustomPlaceholderRegistry()
        self.send_dir = send_dir

    async def run_send(self, send: SendDefinition, verbose: bool = False) -> SendResult:
        """Execute a single send definition."""
        start_time = time.time()
        result = SendResult(send_id=send.name, status="PENDING")

        logger.info(f"Running send: {send.name}")

        try:
            if send.skip:
                result.status = "SKIPPED"
                result.elapsed_ms = int((time.time() - start_time) * 1000)
                return result

            # Execute inject phase
            injected = await self._execute_inject(send)
            result.injected = injected

            if not result.errors:
                result.status = "COMPLETED"
            else:
                result.status = "FAILED"

        except Exception as e:
            logger.exception(f"Send {send.name} execution failed")
            result.status = "FAILED"
            result.errors.append(f"Send execution error: {str(e)}")

        result.elapsed_ms = int((time.time() - start_time) * 1000)
        return result

    async def _execute_inject(self, send: SendDefinition) -> List[Dict[str, Any]]:
        """
        Execute injection phase: injections and scripts, sequential.
        Returns list of injected messages.
        """
        injected_messages = []
        context = {}

        try:
            # Process items sequentially
            for item in send.items:
                if isinstance(item, TestInjection):
                    try:
                        # Build template context
                        template_context = {
                            "sendId": send.name,
                            "uuid": str(__import__('uuid').uuid4()),
                            "now": datetime.now(timezone.utc).isoformat() + "Z",
                            "randomInt": lambda min_val=0, max_val=100: __import__('random').randint(min_val, max_val)
                        }

                        # Add custom placeholders
                        if self.custom_placeholder_registry:
                            placeholders = self.custom_placeholder_registry.get_all_placeholders()
                            for name, func in placeholders.items():
                                try:
                                    template_context[name] = func(template_context)
                                except Exception as e:
                                    logger.warning(f"Failed to execute custom placeholder {name}: {e}")

                        template_context.update(context)

                        # Render and inject
                        rendered_payload = TemplateRenderer.render(item.payload, template_context)
                        rendered_headers = None
                        if item.headers:
                            rendered_headers = {
                                k: TemplateRenderer.render(v, template_context)
                                for k, v in item.headers.items()
                            }

                        # Render key if present
                        rendered_key = None
                        if item.key:
                            rendered_key = TemplateRenderer.render(item.key, template_context)

                        try:
                            payload_obj = json.loads(rendered_payload)
                        except json.JSONDecodeError:
                            payload_obj = rendered_payload

                        # Apply fault injection if configured
                        if item.fault:
                            is_json = isinstance(payload_obj, dict)
                            should_produce, payload_obj = FaultInjector.apply_fault(payload_obj, item.fault, is_json)

                            if not should_produce:
                                logger.info(f"Send injection message to {item.topic} was dropped due to fault injection")
                                continue

                            # Apply random latency if configured
                            random_latency_ms = FaultInjector.get_random_latency_ms(item.fault)
                            if random_latency_ms:
                                logger.debug(f"Applying random latency {random_latency_ms}ms to send injection")
                                await asyncio.sleep(random_latency_ms / 1000.0)

                        # Apply messageKey poison pill if configured
                        if item.fault and item.fault.poison_pill > 0 and 'messageKey' in item.fault.poison_pill_type:
                            if FaultInjector._should_fault(item.fault.poison_pill):
                                rendered_key = FaultInjector.apply_messagekey_poison_pill(rendered_key)

                        self.kafka_client.produce(
                            topic=item.topic,
                            message=payload_obj,
                            headers=rendered_headers,
                            key=rendered_key
                        )

                        # Handle message duplication if configured
                        if item.fault and FaultInjector.should_duplicate(item.fault):
                            logger.info(f"Duplicating send injection message to {item.topic} (fault injection)")
                            self.kafka_client.produce(
                                topic=item.topic,
                                message=payload_obj,
                                headers=rendered_headers,
                                key=rendered_key
                            )

                        injected_msg = InjectedMessage(
                            message_id=item.message_id,
                            topic=item.topic,
                            payload=payload_obj,
                            headers=rendered_headers,
                            timestamp=int(time.time() * 1000),
                            status="ok"
                        )
                        injected_messages.append(injected_msg)

                        logger.info(f"Injected message {item.message_id} to {item.topic}")

                        if item.delay_ms > 0:
                            await asyncio.sleep(item.delay_ms / 1000.0)

                    except Exception as e:
                        logger.error(f"Failed to inject message {item.message_id}: {e}")
                        raise

                elif isinstance(item, TestScript):
                    # Execute script
                    try:
                        script_context = {
                            "current_injections": [asdict(m) for m in injected_messages],
                            "custom_placeholders": self.custom_placeholder_registry.get_all_placeholders() or {},
                            "kafka_client": self.kafka_client,
                            "context": context
                        }
                        exec(item.script, script_context)
                        if "context" in script_context:
                            context.update(script_context["context"])
                    except Exception as e:
                        logger.error(f"Send script failed: {e}")
                        raise

        except Exception as e:
            logger.error(f"Inject phase failed: {e}")
            raise

        return [
            {"message_id": m.message_id, "topic": m.topic, "status": m.status, "payload": m.payload}
            for m in injected_messages
        ]

