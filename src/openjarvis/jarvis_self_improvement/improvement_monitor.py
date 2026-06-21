import logging
import traceback
from typing import Any, Callable

logger = logging.getLogger(__name__)

class ImprovementMonitor:
    """Stage 1: Observation Layer. Hooks into JARVIS functions to detect errors and slow responses."""
    
    def __init__(self, issue_tracker):
        self.issue_tracker = issue_tracker

    def capture_exception(self, module_name: str, e: Exception):
        """Called by JARVIS core when an unhandled exception occurs."""
        error_msg = str(e)
        issue_id = f"crash_{module_name}_{type(e).__name__}"
        
        # We store the stack trace snippet as description
        desc = f"Exception in {module_name}:\n{traceback.format_exc(limit=3)}"
        
        self.issue_tracker.log_issue(
            issue_id=issue_id,
            description=desc,
            severity="critical"
        )

    def log_user_correction(self, context: str, user_transcript: str):
        """Called when a user says 'No', 'Stop', 'Wrong', etc."""
        issue_id = f"user_correction_{context}"
        desc = f"User corrected JARVIS in context '{context}'. Transcript: '{user_transcript}'"
        
        self.issue_tracker.log_issue(
            issue_id=issue_id,
            description=desc,
            severity="medium"
        )
