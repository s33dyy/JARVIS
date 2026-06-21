"""Base classes for JARVIS OS Engines."""

import abc
import asyncio
import logging
from typing import Any, Dict, Optional
from openjarvis.core.events import EventBus

logger = logging.getLogger(__name__)

class BaseEngine(abc.ABC):
    """Abstract base class for all JARVIS background engines.
    
    Engines are autonomous sub-systems that maintain context over specific
    domains of the user's life (e.g., Work, Health, Relationships).
    """

    def __init__(self, name: str, bus: EventBus, config: Any):
        self.name = name
        self.bus = bus
        self.config = config
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the engine's polling loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Engine '{self.name}' started.")

    async def stop(self):
        """Stop the engine's polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"Engine '{self.name}' stopped.")

    async def _loop(self):
        """Internal polling loop."""
        while self._running:
            try:
                await self.poll()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in engine '{self.name}': {e}")
            await asyncio.sleep(self.poll_interval())

    @abc.abstractmethod
    def poll_interval(self) -> int:
        """Return the polling interval in seconds."""
        pass

    @abc.abstractmethod
    async def poll(self):
        """Perform the engine's primary background work (e.g. syncing data)."""
        pass

    @abc.abstractmethod
    async def reflect(self) -> str:
        """Generate a summary or reflection of the engine's current state."""
        pass

    def trigger_proactive(self, message: str, severity: str = "info", dnd_override: bool = False):
        """Trigger a proactive notification to the user via Voice/Dashboard.
        
        Args:
            message: The message to convey.
            severity: 'info', 'warning', 'critical'
            dnd_override: If True, bypasses Do Not Disturb checks.
        """
        # We publish an event that the JARVIS Orchestrator (SystemBuilder/Daemon)
        # will intercept, check DND status, and potentially route to `speak()` or dashboard.
        self.bus.publish(
            "engine.proactive_trigger",
            {
                "engine_name": self.name,
                "message": message,
                "severity": severity,
                "dnd_override": dnd_override,
            }
        )
        logger.debug(f"Engine '{self.name}' triggered proactive alert: {message}")
