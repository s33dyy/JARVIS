export function ReflectionWidget() {
  return (
    <div className="bg-surface border border-border/40 rounded-xl p-5 relative overflow-hidden group hover:border-orange/40 transition-colors">
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-orange to-red opacity-50"></div>
      <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
        <span>🧠</span> Nightly Reflection
      </h3>
      <p className="text-sm text-muted mb-4">JARVIS observations on your day.</p>
      
      <div className="bg-bg/50 p-4 rounded-lg border border-border/30 text-sm leading-relaxed">
        <p className="mb-2"><strong>Today:</strong> Worked 6 hours. Finished deployment. Missed gym.</p>
        <p className="text-orange"><strong>Observation:</strong> You are procrastinating on the frontend. Consider breaking it down into smaller tasks tomorrow.</p>
      </div>
    </div>
  );
}
