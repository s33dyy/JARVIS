import json
import re
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

_LAST_INTERACTION_FILE = Path.home() / ".jarvis" / "last_interaction.json"

_CORRECTION_PATTERNS = [
    r"^(no\b|stop\b|cancel\b|wait\b|hang on\b|that's wrong\b|incorrect\b)",
    r"^(i meant|i said|i wanted)",
    r"^(not |don't |do not )",
]
_COMPILED_CORRECTION_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _CORRECTION_PATTERNS]

def save_interaction(user_input: str, intent_or_action: str, response: str, success: bool = True) -> None:
    """Saves the last turn for evaluation on the next turn."""
    data = {
        "input": user_input,
        "prediction": intent_or_action,
        "response": response,
        "correct": success,
        "ts": datetime.now().isoformat()
    }
    _LAST_INTERACTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAST_INTERACTION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def get_last_interaction() -> Optional[dict]:
    if not _LAST_INTERACTION_FILE.exists():
        return None
    try:
        return json.loads(_LAST_INTERACTION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

def evaluate_correction(current_input: str) -> Tuple[bool, Optional[str]]:
    """
    Checks if the user's current input is correcting JARVIS's previous action.
    Returns (is_correction, spoken_apology).
    """
    current_input = current_input.strip()
    is_correction = False
    
    for pat in _COMPILED_CORRECTION_PATTERNS:
        if pat.search(current_input):
            is_correction = True
            break
            
    if not is_correction:
        return False, None
        
    last = get_last_interaction()
    if not last:
        return False, None
        
    # User is correcting us. Log the failure!
    try:
        from jarvis_error_tracker import record_error
        # Determine error type based on prediction prefix (e.g., intent_xxx vs llm_response)
        error_type = "intent" if last["prediction"].startswith("intent_") else "llm"
        record_error(error_type, last["input"], last["prediction"])
    except Exception as e:
        print(f"[Evaluator] Failed to record error: {e}")
        
    # Mark the last interaction as incorrect
    last["correct"] = False
    _LAST_INTERACTION_FILE.write_text(json.dumps(last, indent=2), encoding="utf-8")
    
    apology = "I may have misunderstood. Let's try again. What did you mean?"
    return True, apology
