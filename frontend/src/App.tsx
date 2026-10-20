import { useCallback, useEffect, useMemo, useState } from 'react'
import { Info, Lock, RefreshCw, ServerCog, TriangleAlert } from 'lucide-react'
import { runAnalysis, type LoadResult } from '@/api'
import type { DecisionStatus } from '@/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import ThemeToggle from '@/components/ThemeToggle'
import Workflow from '@/components/Workflow'
import InputStatus from '@/components/InputStatus'
import SummaryCards from '@/components/SummaryCards'
import ResultsTable from '@/components/ResultsTable'
import DetailPanel from '@/components/DetailPanel'

export default function App() {
  const [state, setState] = useState<LoadResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<DecisionStatus | 'all'>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setState(await runAnalysis())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load analysis')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const visible = useMemo(
    () => (state?.data.results ?? []).filter((r) => filter === 'all' || r.decision === filter),
    [state, filter],
  )
  const selected = state?.data.results.find((r) => r.workload_id === selectedId) ?? null

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground"><ServerCog className="size-5" aria-hidden /></span>
          <div>
            <h1 className="text-xl leading-tight font-semibold">Kubernetes FinOps Agent</h1>
            <p className="text-sm text-muted-foreground">Evidence-based, multi-agent resource recommendations</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline"><Lock aria-hidden />Recommendation-only</Badge>
          {state && (
            <Badge variant="outline" className={cn(state.source === 'api' && 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300')}>
              {state.source === 'api' ? `Live API · ${state.data.mode}` : 'Mock data · API offline'}
            </Badge>
          )}
          <ThemeToggle />
          <Button onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn(loading && 'animate-spin')} aria-hidden />{loading ? 'Running…' : 'Run analysis'}
          </Button>
        </div>
      </header>

      {error && (
        <p role="alert" className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          <TriangleAlert className="size-4 shrink-0" aria-hidden />{error}
        </p>
      )}
      {loading && !state && <p className="text-sm text-muted-foreground">Loading…</p>}

      {state && (
        <>
          {state.data.warnings.map((w) => (
            <p key={w} className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
              <Info className="size-4 shrink-0" aria-hidden />{w}
            </p>
          ))}
          <Workflow data={state.data} />
          <InputStatus data={state.data} />
          <SummaryCards summary={state.data.summary} active={filter} onFilter={setFilter} />
          <div className="grid items-start gap-6 lg:grid-cols-[1fr_440px]">
            <ResultsTable results={visible} selectedId={selectedId} onSelect={setSelectedId} />
            {selected ? (
              <DetailPanel key={selected.workload_id} result={selected} />
            ) : (
              <p className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">Select a workload to see evidence, the critic's audit trail and the proposed patch.</p>
            )}
          </div>
          <footer className="border-t pt-4 text-xs text-muted-foreground">
            Prototype using local/mock data. Savings are illustrative estimates, not guaranteed bill reductions. Every change requires human approval; nothing is applied to a cluster.
          </footer>
        </>
      )}
    </div>
  )
}