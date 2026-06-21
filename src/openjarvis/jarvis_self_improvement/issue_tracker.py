import os
import json
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

# Basic impact multipliers
SEVERITY_WEIGHTS = {
    "low": 10,
    "medium": 30,
    "high": 60,
    "critical": 100
}

class IssueTracker:
    """Stores, tracks, and prioritizes issues for the Self Improvement Engine."""
    
    def __init__(self, db_path: str = None):
        if not db_path:
            self.db_path = os.path.expanduser("~/.jarvis/issues.json")
        else:
            self.db_path = db_path
            
        self.issues = self._load_issues()

    def _load_issues(self) -> Dict[str, Any]:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_issues(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with open(self.db_path, "w") as f:
            json.dump(self.issues, f, indent=4)

    def log_issue(self, issue_id: str, description: str, severity: str = "medium"):
        """Logs a new occurrence of an issue."""
        if issue_id not in self.issues:
            self.issues[issue_id] = {
                "id": issue_id,
                "description": description,
                "severity": severity,
                "count": 0,
                "status": "open"
            }
        
        self.issues[issue_id]["count"] += 1
        self._save_issues()
        logger.info(f"Issue tracked: {issue_id} (count: {self.issues[issue_id]['count']})")

    def prioritize_issues(self) -> List[Dict[str, Any]]:
        """
        Returns a sorted list of open issues based on:
        Score = Impact x Frequency x Severity
        """
        scored_issues = []
        for issue in self.issues.values():
            if issue.get("status") != "open":
                continue
                
            count = issue.get("count", 1)
            severity = issue.get("severity", "low").lower()
            base_score = SEVERITY_WEIGHTS.get(severity, 10)
            
            # Simple scoring metric
            final_score = base_score * count
            
            issue["score"] = final_score
            scored_issues.append(issue)
            
        # Sort highest score first
        scored_issues.sort(key=lambda x: x["score"], reverse=True)
        return scored_issues

    def mark_resolved(self, issue_id: str):
        """Marks an issue as resolved post-deployment."""
        if issue_id in self.issues:
            self.issues[issue_id]["status"] = "resolved"
            self._save_issues()
