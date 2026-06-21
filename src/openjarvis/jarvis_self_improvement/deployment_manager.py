import os
import subprocess
import logging

logger = logging.getLogger(__name__)

class DeploymentManager:
    """Handles Git branching and deployment for self-improvement."""
    
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def _run_git(self, *args) -> str:
        cmd = ["git", "-C", self.repo_path, *args]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")
            raise RuntimeError(f"Git error: {result.stderr}")
        return result.stdout.strip()

    def create_improvement_branch(self, issue_id: str) -> str:
        """Create and checkout a new branch for the improvement."""
        branch_name = f"auto-improvement-{issue_id}"
        logger.info(f"Creating branch: {branch_name}")
        
        # Ensure we are on main and up to date
        self._run_git("checkout", "main")
        
        try:
            self._run_git("checkout", "-b", branch_name)
        except RuntimeError:
            # If branch exists, just check it out
            self._run_git("checkout", branch_name)
            
        return branch_name

    def commit_changes(self, issue_id: str, message: str) -> bool:
        """Commit the changes proposed by Antigravity."""
        try:
            self._run_git("add", ".")
            
            # Check if there are changes
            status = self._run_git("status", "--porcelain")
            if not status:
                logger.info("No changes to commit.")
                return False
                
            commit_msg = f"[Self-Improvement] {issue_id}: {message}"
            self._run_git("commit", "-m", commit_msg)
            logger.info(f"Committed changes for {issue_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to commit changes: {e}")
            return False

    def deploy_to_main(self, branch_name: str) -> bool:
        """Merge the improvement branch into main."""
        logger.info(f"Deploying {branch_name} to main...")
        try:
            self._run_git("checkout", "main")
            self._run_git("merge", "--no-ff", branch_name, "-m", f"Merge improvement {branch_name}")
            return True
        except Exception as e:
            logger.error(f"Merge failed: {e}")
            self._run_git("merge", "--abort")
            return False
