import os
import json
import time
from pathlib import Path

class MemoryManager:
    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root)
        self.memory_file = self.workspace_root / "jarvis_memory.json"
        self._memory = self._load()

    def _load(self):
        if self.memory_file.exists():
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[JARVIS] [ERR] Failed to load memory file: {e}")
        # Default structure
        return {
            "facts": [],
            "preferences": [],
            "notes": [],
            "instructions": [],
            "last_updated": time.time()
        }

    def save(self):
        try:
            self._memory["last_updated"] = time.time()
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self._memory, f, indent=4)
        except Exception as e:
            print(f"[JARVIS] [ERR] Failed to save memory file: {e}")

    def add_fact(self, fact: str, category: str):
        valid_categories = ["preference", "fact", "note", "instruction"]
        # Map back to plural keys if needed, but simple mapping is fine
        cat_key = category + "s" if category in valid_categories else "notes"
        
        if cat_key not in self._memory:
            self._memory[cat_key] = []
            
        if fact not in self._memory[cat_key]:
            self._memory[cat_key].append(fact)
            self.save()
            return True
        return False

    def get_all(self):
        return self._memory

    def format_for_context(self):
        if not any([self._memory.get("facts"), self._memory.get("preferences"), self._memory.get("notes"), self._memory.get("instructions")]):
            return ""
            
        context = []
        if self._memory.get("preferences"):
            context.append("User Preferences:")
            for p in self._memory["preferences"]:
                context.append(f"- {p}")
        
        if self._memory.get("facts"):
            context.append("Facts & Information:")
            for f in self._memory["facts"]:
                context.append(f"- {f}")
                
        if self._memory.get("instructions"):
            context.append("Specific Instructions/Rules:")
            for i in self._memory["instructions"]:
                context.append(f"- {i}")
                
        if self._memory.get("notes"):
            context.append("General Notes:")
            for n in self._memory["notes"]:
                context.append(f"- {n}")

        return "\n".join(context)
