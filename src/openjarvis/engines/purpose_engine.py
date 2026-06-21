"""JARVIS Purpose Engine."""

import logging
from typing import Any
from openjarvis.engines.base_engine import BaseEngine
from openjarvis.core.events import EventBus

logger = logging.getLogger(__name__)

PURPOSE_STATEMENT = """
# PURPOSE ENGINE DIRECTIVE

You are JARVIS. You exist to:
1. Reduce friction.
2. Increase productivity.
3. Help the user achieve their goals.
4. Maintain relationships.
5. Preserve knowledge.
6. Protect time.
7. Improve life quality.

Every action you take should implicitly answer: "Why am I doing this? How does this serve the user's goals?"
If an action does not serve these goals, you should question it.
"""

class PurposeEngine(BaseEngine):
    """The Purpose Engine injects foundational alignment into the system."""

    def __init__(self, name: str, bus: EventBus, config: Any):
        super().__init__(name, bus, config)

    def poll_interval(self) -> int:
        return 3600  # Rarely needs polling, operates via context injection

    async def poll(self):
        # The purpose engine doesn't actively poll external APIs.
        pass

    async def reflect(self) -> str:
        return "Purpose Alignment: Active."

    def get_purpose_context(self) -> str:
        """Return the core purpose directive to be injected into LLM prompts."""
        return PURPOSE_STATEMENT
