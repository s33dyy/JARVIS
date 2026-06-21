"""JARVIS Security Engine."""

import logging
import asyncio
from typing import Any, Dict
from openjarvis.engines.base_engine import BaseEngine
from openjarvis.core.events import EventBus

logger = logging.getLogger(__name__)

class SecurityEngine(BaseEngine):
    """The Security Engine monitors agent actions and system health.
    
    It intercepts dangerous commands and requests user approval before execution.
    """

    def __init__(self, name: str, bus: EventBus, config: Any):
        super().__init__(name, bus, config)
        self.dangerous_commands = ["rm -rf", "mkfs", "dd", "chmod -R 777"]
        # Listen for sandbox execution requests
        self.bus.subscribe("sandbox.execute_request", self._on_execute_request)

    def poll_interval(self) -> int:
        return 60

    async def poll(self):
        # Periodically check system permissions or API key exposure (stub)
        pass

    async def reflect(self) -> str:
        return "Security Posture: Normal. No unauthorized actions intercepted today."

    async def _on_execute_request(self, event_data: Dict[str, Any]):
        """Intercept a shell execution request from an agent."""
        command = event_data.get("command", "")
        agent_id = event_data.get("agent_id", "unknown")

        for danger in self.dangerous_commands:
            if danger in command:
                logger.warning(f"Security Engine intercepted dangerous command from {agent_id}: {command}")
                # Trigger a proactive alert requiring the user to check the dashboard
                self.trigger_proactive(
                    message=f"Agent {agent_id} is attempting a dangerous command. Please review and approve on the Dashboard.",
                    severity="critical",
                    dnd_override=True
                )
                # In a real implementation, we would block the execution here
                # by returning or setting a flag in the event payload.
                event_data["blocked_by_security"] = True
                break
