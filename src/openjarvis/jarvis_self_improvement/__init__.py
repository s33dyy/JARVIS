import logging
import asyncio
from .issue_tracker import IssueTracker
from .improvement_monitor import ImprovementMonitor
from .antigravity_client import AntigravityClient
from .deployment_manager import DeploymentManager
from .rollback_manager import RollbackManager
from .validation_engine import ValidationEngine

logger = logging.getLogger(__name__)

class SelfImprovementOrchestrator:
    """
    Main controller for the 10-Stage Self Improvement workflow.
    """
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        
        self.tracker = IssueTracker()
        self.monitor = ImprovementMonitor(self.tracker)
        
        self.client = AntigravityClient(workspace_path)
        self.deployment = DeploymentManager(workspace_path)
        self.rollback = RollbackManager(workspace_path)
        self.validator = ValidationEngine(workspace_path)

    async def run_nightly_analysis(self) -> str:
        """
        Stage 2 & 3: Issue Detection and Prioritization.
        Called by JARVIS cron at 00:00.
        """
        issues = self.tracker.prioritize_issues()
        if not issues:
            return "No critical issues detected for self-improvement."
            
        top_issue = issues[0]
        
        # We only auto-proceed for issues with high enough scores
        if top_issue.get("score", 0) < 50:
            return f"Top issue '{top_issue['id']}' score ({top_issue['score']}) is below threshold."
            
        logger.info(f"Prioritized issue: {top_issue['id']}")
        
        # Stage 4 & 5: Improvement Proposal & Antigravity Analysis
        proposal = await self.client.analyze_and_propose(top_issue)
        
        # Stage 6 is HUMAN APPROVAL. We return the proposal to JARVIS,
        # which will speak it to the user and ask for permission to apply.
        return f"Issue: {top_issue['description']}\n\nAntigravity Proposal:\n{proposal}\n\n[ISSUE_ID:{top_issue['id']}]"

    async def apply_approved_improvement(self, issue_id: str, proposal_text: str) -> bool:
        """
        Stage 7-10: Implementation, Validation, Deployment, Observation.
        Called when the user says "Approve".
        """
        logger.info(f"User approved improvement for {issue_id}")
        
        # Stage 7: Implementation (DeploymentManager creates branch)
        branch = self.deployment.create_improvement_branch(issue_id)
        
        # Note: In a true autonomous setup, Antigravity would have ALREADY edited files.
        # So we just commit what is currently staged/modified.
        self.deployment.commit_changes(issue_id, "Applied Antigravity changes.")
        
        # Stage 8: Validation
        if not self.validator.run_tests():
            logger.error("Validation failed. Rolling back local changes.")
            self._run_git("reset", "--hard", "HEAD")
            self._run_git("checkout", "main")
            return False
            
        # Stage 9: Deployment
        success = self.deployment.deploy_to_main(branch)
        if success:
            self.tracker.mark_resolved(issue_id)
            return True
            
        return False
        
    def _run_git(self, *args):
        import subprocess
        subprocess.run(["git", "-C", self.workspace_path, *args])
