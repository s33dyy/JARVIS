import logging
import subprocess

logger = logging.getLogger(__name__)

class RollbackManager:
    """Provides git-based rollback mechanisms for deployed improvements."""
    
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def _run_git(self, *args) -> str:
        cmd = ["git", "-C", self.repo_path, *args]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")
            raise RuntimeError(f"Git error: {result.stderr}")
        return result.stdout.strip()

    def rollback_improvement(self, branch_name: str) -> bool:
        """
        Reverts the merge commit associated with an improvement branch.
        """
        logger.warning(f"Initiating rollback for improvement from {branch_name}...")
        try:
            self._run_git("checkout", "main")
            # In a real setup, we would find the merge commit hash and revert it.
            # A simple approach is to reset to HEAD~1 if it was the last commit.
            # For robustness, we search for the commit matching the branch name.
            log_output = self._run_git("log", "--oneline", "-n", "10")
            
            commit_hash = None
            for line in log_output.splitlines():
                if f"Merge improvement {branch_name}" in line:
                    commit_hash = line.split()[0]
                    break
                    
            if not commit_hash:
                logger.error(f"Could not find merge commit for {branch_name} to rollback.")
                return False
                
            # Revert the merge commit (requires -m 1 to specify mainline)
            self._run_git("revert", "-m", "1", "--no-edit", commit_hash)
            logger.info(f"Successfully rolled back {branch_name} (commit {commit_hash})")
            return True
            
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            # If revert fails (e.g. conflicts), abort the revert
            try:
                self._run_git("revert", "--abort")
            except:
                pass
            return False
