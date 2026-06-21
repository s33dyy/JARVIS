"""JARVIS Health Engine."""

import logging
from typing import Any
from openjarvis.engines.base_engine import BaseEngine
from openjarvis.core.events import EventBus

logger = logging.getLogger(__name__)

class HealthEngine(BaseEngine):
    """Tracks physical health, sleep, and screen time."""

    def __init__(self, name: str, bus: EventBus, config: Any):
        super().__init__(name, bus, config)
        # Settings config determines if we ping Apple Health or prompt user.
        self.ingestion_mode = getattr(config, "health_ingestion", "manual")

    def poll_interval(self) -> int:
        return 14400  # Poll every 4 hours

    async def poll(self):
        if self.ingestion_mode == "manual":
            # Just an example of a proactive prompt
            pass
        elif self.ingestion_mode == "api":
            logger.info("HealthEngine: Syncing from Health API...")

    async def reflect(self) -> str:
        return "Health Status: Slept 6.5 hours last night. Need more water."
