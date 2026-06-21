import { EnergyDashboard } from '../components/Dashboard/EnergyDashboard';
import { CostComparison } from '../components/Dashboard/CostComparison';
import { TraceDebugger } from '../components/Dashboard/TraceDebugger';
import { GoalWidget } from '../components/Dashboard/GoalWidget';
import { CRMWidget } from '../components/Dashboard/CRMWidget';
import { ReflectionWidget } from '../components/Dashboard/ReflectionWidget';
import { AgentMarketplace } from '../components/Dashboard/AgentMarketplace';
import { ApprovalNotification } from '../components/Dashboard/ApprovalNotification';

export function DashboardPage() {
  const now = new Date();
  const stamp = now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <header className="mb-6">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              JARVIS Personal OS
            </h1>
            <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {stamp}
            </div>
          </div>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            Proactive tracking for your work, health, relationships, and goals.
          </p>
        </header>

        <ApprovalNotification />

        {/* New OS Engine Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          <GoalWidget />
          <CRMWidget />
          <ReflectionWidget />
        </div>
        
        <div className="mb-6">
          <AgentMarketplace />
        </div>

        <div className="my-8 border-t border-border/40 pt-6">
          <h2 className="text-md font-semibold mb-4 text-muted">System Telemetry</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
            <EnergyDashboard />
            <CostComparison />
          </div>
          <TraceDebugger />
        </div>
      </div>
    </div>
  );
}
