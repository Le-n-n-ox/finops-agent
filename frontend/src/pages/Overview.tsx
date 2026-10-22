import SummaryCards from '@/components/SummaryCards'
import SavingsPotential from '@/components/SavingsPotential'
import TrendChart from '@/components/TrendChart'
import { useAnalysis } from '@/state/analysis-context'
import { useRouter } from '@/state/router-context'
import type { DecisionStatus } from '@/types'

/**
 * Overview: the money, and whether it is moving.
 *
 * This is the page a manager opens. It answers one question — how much is on the table, how much
 * of it are we allowed to act on, and is that number going up or down — and it deliberately does
 * not answer any others. The workload-by-workload detail lives on its own page.
 */
export default function Overview() {
  const { state, dashboard, filter, setFilter } = useAnalysis()
  const { navigate } = useRouter()

  if (!state) return null

  // A decision card is a drill-in: it filters the workload list, so it takes you there.
  const drill = (f: DecisionStatus | 'all') => {
    setFilter(f)
    navigate('/workloads')
  }

  return (
    <div className="space-y-6">
      <SummaryCards summary={state.data.summary} active={filter} onFilter={drill} />

      <SavingsPotential results={state.data.results} />

      {!!state.data.top_opportunities?.length && (
        <section className="rounded-xl border bg-card p-4" aria-label="Top ranked opportunities">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 className="font-semibold">Top opportunities</h2>
            <span className="text-xs text-muted-foreground">Ranked from approved recommendations · top {state.data.top_n_findings ?? 5}</span>
          </div>
          <ol className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            {state.data.top_opportunities.map((item, index) => (
              <li key={item.workload_id}>
                <button
                  onClick={() => navigate(`/workloads?workload=${encodeURIComponent(item.workload_id)}`)}
                  className="w-full rounded-lg border p-3 text-left transition-colors hover:bg-muted/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                >
                  <p className="text-xs text-muted-foreground">#{index + 1} · priority {item.priority_score.toFixed(2)}</p>
                  <p className="font-medium">{item.workload_id}</p>
                  <p className="text-sm">${item.monthly_savings_usd.toFixed(2)} / month</p>
                  <p className="text-xs text-muted-foreground">{item.confidence_score.toFixed(0)}% confidence · {item.risk_level} risk</p>
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}

      <TrendChart trend={dashboard?.trend ?? []} />
    </div>
  )
}
