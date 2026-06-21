import { useState } from "react";

export function ApprovalNotification() {
  const [visible, setVisible] = useState(true);

  if (!visible) return null;

  return (
    <div className="bg-surface border border-accent/50 rounded-xl p-4 shadow-lg flex items-start gap-4 mb-6 relative overflow-hidden animate-pulse-slow">
      <div className="absolute top-0 left-0 w-1 h-full bg-accent"></div>
      <div className="text-2xl mt-1">🔧</div>
      <div className="flex-1">
        <h4 className="text-sm font-semibold text-text">JARVIS Self-Improvement Alert</h4>
        <p className="text-xs text-muted mt-1">
          The code fix for <strong>jarvis_memory.py</strong> is ready for your review.
        </p>
        <div className="flex gap-2 mt-3">
          <button 
            onClick={() => setVisible(false)}
            className="px-3 py-1 bg-accent text-white rounded text-xs hover:bg-accent/80 transition-colors"
          >
            Approve & Merge
          </button>
          <button 
            onClick={() => setVisible(false)}
            className="px-3 py-1 bg-bg border border-border text-muted rounded text-xs hover:text-text transition-colors"
          >
            Review Diff
          </button>
          <button 
            onClick={() => setVisible(false)}
            className="px-3 py-1 bg-bg border border-border text-red rounded text-xs hover:bg-red/10 transition-colors ml-auto"
          >
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}
