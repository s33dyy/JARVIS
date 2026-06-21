import { useState } from "react";

export function CRMWidget() {
  const [contacts] = useState([
    { name: "Rahul", status: "Needs Catch-up", last: "11 days ago" },
    { name: "Team Lead", status: "Meeting Tomorrow", last: "Yesterday" }
  ]);

  return (
    <div className="bg-surface border border-border/40 rounded-xl p-5 relative overflow-hidden group hover:border-green/40 transition-colors">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-green to-accent opacity-50"></div>
      <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
        <span>👥</span> Personal CRM
      </h3>
      <p className="text-sm text-muted mb-4">Managing relationships & context.</p>
      
      <div className="space-y-3">
        {contacts.map((c, i) => (
          <div key={i} className="flex justify-between items-center bg-bg/50 p-2 rounded-lg border border-border/30">
            <div>
              <div className="text-sm font-medium">{c.name}</div>
              <div className="text-xs text-muted">Last: {c.last}</div>
            </div>
            <span className="text-xs bg-green/10 text-green px-2 py-1 rounded">
              {c.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
