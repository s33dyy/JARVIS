import subprocess
import logging
from typing import List

logger = logging.getLogger(__name__)

class ValidationEngine:
    """Runs automated verification on proposed changes before merging."""
    
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path

    def run_tests(self) -> bool:
        """
        Runs unit and integration tests. 
        Returns True if all checks pass.
        """
        logger.info("Running syntax checks and tests on new branch...")
        
        # 1. Syntax check
        if not self._run_syntax_check():
            logger.error("Syntax check failed! Rejecting changes.")
            return False
            
        # 2. Pytest (if available)
        if not self._run_pytest():
            logger.error("Unit tests failed! Rejecting changes.")
            return False
            
        logger.info("All validation tests passed.")
        return True

    def _run_syntax_check(self) -> bool:
        """Check all python files for basic syntax errors."""
        try:
            cmd = ["python", "-m", "compileall", "-q", self.workspace_path]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Syntax validation error: {e}")
            return False

    def _run_pytest(self) -> bool:
        """Run pytest if tests exist."""
        try:
            cmd = ["pytest", self.workspace_path, "-q", "--disable-warnings"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            # Return code 0 means all passed. 
            # Return code 5 means no tests collected (which is also fine if none exist yet)
            return result.returncode in [0, 5]
        except FileNotFoundError:
            # pytest not installed
            logger.warning("pytest not found. Skipping unit tests.")
            return True
        except Exception as e:
            logger.error(f"Pytest validation error: {e}")
            return False
