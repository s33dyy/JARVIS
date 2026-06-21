"""JARVIS Goal Engine."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List
from openjarvis.engines.base_engine import BaseEngine
from openjarvis.core.events import EventBus

logger = logging.getLogger(__name__)

class GoalEngine(BaseEngine):
    """Tracks long-term user goals and assesses if tasks align with them."""

    def __init__(self, name: str, bus: EventBus, config: Any):
        super().__init__(name, bus, config)
        self.goals_file = Path(Path.home()) / ".jarvis" / "goals.json"
        self.goals: List[Dict[str, Any]] = []
        self._load_goals()

    def _load_goals(self):
        if self.goals_file.exists():
            try:
                with open(self.goals_file, "r") as f:
                    self.goals = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load goals: {e}")
        else:
            self.goals = [
                {"id": 1, "title": "Become ML engineer", "progress": 40},
                {"id": 2, "title": "Build startup", "progress": 15},
            ]
            self._save_goals()

    def _save_goals(self):
        self.goals_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.goals_file, "w") as f:
            json.dump(self.goals, f, indent=2)

    def poll_interval(self) -> int:
        return 86400  # Poll once a day

    async def poll(self):
        # Could prompt the user weekly: "You made 5% progress on ML engineering."
        logger.info("GoalEngine polling...")

    async def reflect(self) -> str:
        active = [g['title'] for g in self.goals if g.get('progress', 0) < 100]
        return f"Active Goals: {', '.join(active)}."

    def evaluate_task(self, task_description: str) -> str:
        """Called when a new task is detected to check alignment."""
        # Stub: Imagine asking an LLM if task_description aligns with self.goals
        return "This task appears aligned with your goal to 'Build startup'."
