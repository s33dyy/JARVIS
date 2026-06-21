import { useState, useEffect } from "react";

export function GoalWidget() {
  const [goals, setGoals] = useState([
    { id: 1, title: "Become ML engineer", progress: 40 },
    { id: 2, title: "Build startup", progress: 15 },
  ]);

  return (
    <div className="bg-surface border border-border/40 rounded-xl p-5 relative overflow-hidden group hover:border-accent/40 transition-colors">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-accent to-purple opacity-50"></div>
      <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
        <span>🎯</span> Goals & Alignment
      </h3>
      <p className="text-sm text-muted mb-4">JARVIS tracks your long-term vectors.</p>
      
      <div className="space-y-4">
        {goals.map((g) => (
          <div key={g.id}>
            <div className="flex justify-between text-sm mb-1">
              <span>{g.title}</span>
              <span className="text-accent">{g.progress}%</span>
            </div>
            <div className="h-2 bg-bg rounded-full overflow-hidden">
              <div 
                className="h-full bg-accent" 
                style={{ width: `${g.progress}%` }}
              ></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
