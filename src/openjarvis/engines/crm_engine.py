"""JARVIS CRM Engine."""

import json
import logging
from pathlib import Path
from typing import Any, Dict
from openjarvis.engines.base_engine import BaseEngine
from openjarvis.core.events import EventBus

logger = logging.getLogger(__name__)

class CRMEngine(BaseEngine):
    """Personal Relationship Management."""

    def __init__(self, name: str, bus: EventBus, config: Any):
        super().__init__(name, bus, config)
        self.crm_file = Path(Path.home()) / ".jarvis" / "crm.json"
        self.contacts: Dict[str, Any] = {}
        self._load_crm()

    def _load_crm(self):
        if self.crm_file.exists():
            try:
                with open(self.crm_file, "r") as f:
                    self.contacts = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load CRM: {e}")
        else:
            self.contacts = {
                "Rahul": {
                    "likes": ["Python", "Machine Learning"],
                    "last_contact": "2026-06-10",
                    "notes": ["Interview next week"]
                }
            }
            self._save_crm()

    def _save_crm(self):
        self.crm_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.crm_file, "w") as f:
            json.dump(self.contacts, f, indent=2)

    def poll_interval(self) -> int:
        return 43200  # Twice a day

    async def poll(self):
        # Check if anyone hasn't been contacted in a long time
        pass

    async def reflect(self) -> str:
        return f"CRM: Tracking {len(self.contacts)} key relationships."

    def get_context_for_person(self, name: str) -> str:
        if name in self.contacts:
            data = self.contacts[name]
            notes = ", ".join(data.get("notes", []))
            return f"Known about {name}: Last contacted {data.get('last_contact')}. Notes: {notes}."
        return ""
