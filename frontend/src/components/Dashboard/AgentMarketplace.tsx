import { useState } from "react";

export function AgentMarketplace() {
  const [agents] = useState([
    { name: "Antigravity", role: "Creative & Media UI", status: "Idle", icon: "✨" },
    { name: "Codex", role: "Backend & Logic", status: "Working", icon: "⚙️" },
    { name: "DeepResearch", role: "Web Browsing", status: "Idle", icon: "🔍" },
  ]);

  return (
    <div className="bg-surface border border-border/40 rounded-xl p-5 lg:col-span-2">
      <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
        <span>🤖</span> Agent Marketplace & Manager
      </h3>
      <p className="text-sm text-muted mb-4">JARVIS delegates to specialized sub-agents.</p>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {agents.map((a, i) => (
          <div key={i} className="bg-bg/50 border border-border/30 p-4 rounded-xl flex items-center gap-4">
            <div className="text-2xl">{a.icon}</div>
            <div>
              <div className="font-medium text-sm flex items-center gap-2">
                {a.name}
                <span className={`w-2 h-2 rounded-full ${a.status === 'Working' ? 'bg-orange animate-pulse' : 'bg-green'}`}></span>
              </div>
              <div className="text-xs text-muted">{a.role}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
