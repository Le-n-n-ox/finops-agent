import { useMemo, useState } from 'react'
import { ArrowDown, ArrowRight, ArrowUp, ArrowUpDown, Search, SearchX, ShieldQuestion } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DecisionBadge, RiskText } from './DecisionBadge'
import { cn } from '@/lib/utils'
import type { RiskLevel, WorkloadResult, WorkloadRow } from '@/types'

interface Props {
  results: WorkloadResult[]
  selectedId: string | null
  onSelect: (id: string) => void
  /** Per-workload data quality and the latest human action, from GET /api/workloads. */
  workloadRows?: WorkloadRow[] | null
}

type SortKey = 'workload' | 'risk' | 'saving'
const RISK_RANK: Record<RiskLevel, number> = { low: 0, medium: 1, high: 2 }
const fmt = (n: number | null | undefined, unit: string) => (n == null ? '—' : `${n.toLocaleString()} ${unit}`)

/** What the optimizer found, whether or not the critic let it through. */
const potential = (r: WorkloadResult) =>
  (r.proposal.estimated_monthly_saving_usd ?? 0) + (r.proposal.suppressed_saving_usd ?? 0)

function SortHead({ label, k, sort, onSort, className }: { label: string; k: SortKey; sort: { key: SortKey; dir: 1 | -1 } | null; onSort: (k: SortKey) => void; className?: string }) {
  const active = sort?.key === k
  const Icon = !active ? ArrowUpDown : sort.dir === 1 ? ArrowUp : ArrowDown
  return (
    <TableHead className={className} aria-sort={active ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
      <button onClick={() => onSort(k)} className="inline-flex items-center gap-1 uppercase outline-none hover:text-foreground focus-visible:text-foreground">
        {label}<Icon className="size-3" aria-hidden />
      </button>
    </TableHead>
  )
}

export default function ResultsTable({ results, selectedId, onSelect, workloadRows }: Props) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 } | null>(null)

  // The history endpoint knows the last thing a human did with each workload. Showing it inline
  // stops a reviewer accepting a recommendation they already rejected.
  const byWorkload = useMemo(
    () => new Map((workloadRows ?? []).map((r) => [r.workload_id, r])),
    [workloadRows],
  )

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = q ? results.filter((r) => `${r.workload_id} ${r.namespace}`.toLowerCase().includes(q)) : results
    if (!sort) return filtered
    // Sort on the potential, not the counted amount: the counted amount is 0 for every workload the
    // critic deferred, so sorting on it would tie eight rows at zero and bury the real findings.
    const val = (r: WorkloadResult) =>
      sort.key === 'workload'
        ? r.workload_id
        : sort.key === 'risk'
          ? RISK_RANK[r.risk_level]
          : potential(r)
    return [...filtered].sort((a, b) => (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * sort.dir)
  }, [results, query, sort])

  const onSort = (key: SortKey) =>
    setSort((s) => (s?.key !== key ? { key, dir: 1 } : s.dir === 1 ? { key, dir: -1 } : null))

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <Search className="size-4 text-muted-foreground" aria-hidden />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search workload or namespace…"
          aria-label="Search workloads"
          className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </div>
      {rows.length === 0 ? (
        <div className="space-y-3 p-10 text-center">
          <p className="text-sm text-muted-foreground">
            {results.length === 0
              ? 'This analysis produced no workloads.'
              : query.trim()
                ? `Nothing matches “${query.trim()}”.`
                : 'No workloads have this decision.'}
          </p>
          {results.length > 0 && query.trim() && (
            <Button variant="outline" size="sm" onClick={() => setQuery('')}>
              <SearchX aria-hidden />Clear search
            </Button>
          )}
        </div>
      ) : (
        <Table>
          <caption className="sr-only">
            Workloads analysed, with the critic's decision and the savings found. A saving shown as
            &ldquo;held&rdquo; was found by the optimizer but refused by a safety rule.
          </caption>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <SortHead label="Workload" k="workload" sort={sort} onSort={onSort} />
              <TableHead>Decision</TableHead>
              <SortHead label="Risk" k="risk" sort={sort} onSort={onSort} />
              <TableHead>CPU request</TableHead>
              <TableHead>Memory request</TableHead>
              <SortHead label="Saving / mo" k="saving" sort={sort} onSort={onSort} className="text-right" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const { current, proposed } = r.proposal
              const found = potential(r)
              const counted = r.monthly_savings_estimate_usd
              const meta = byWorkload.get(r.workload_id)
              return (
                <TableRow
                  key={r.workload_id}
                  tabIndex={0}
                  aria-selected={selectedId === r.workload_id}
                  data-state={selectedId === r.workload_id ? 'selected' : undefined}
                  onClick={() => onSelect(r.workload_id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(r.workload_id) } }}
                  className="cursor-pointer outline-none focus-visible:bg-muted"
                >
                  <TableCell>
                    <p className="font-medium">{r.workload_id}</p>
                    <p className="text-xs text-muted-foreground">{r.namespace}</p>
                    {meta && (
                      <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                        <span
                          title={`Data quality ${meta.data_quality}/100`}
                          className={cn(
                            'inline-flex items-center gap-0.5 rounded px-1 py-px',
                            meta.data_quality < 50
                              ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
                              : 'bg-muted',
                          )}
                        >
                          <ShieldQuestion className="size-2.5" aria-hidden />{Math.round(meta.data_quality)}
                        </span>
                        {meta.latest_action && (
                          <span
                            title={`Last human action: ${meta.latest_action}`}
                            className={cn(
                              'rounded px-1 py-px',
                              meta.latest_action === 'REJECTED'
                                ? 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300'
                                : meta.latest_action === 'ACCEPTED_FOR_IMPLEMENTATION'
                                  ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                                  : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
                            )}
                          >
                            {meta.latest_action === 'REJECTED'
                              ? 'rejected before'
                              : meta.latest_action === 'ACCEPTED_FOR_IMPLEMENTATION'
                                ? 'accepted before'
                                : 'needs investigation'}
                          </span>
                        )}
                      </p>
                    )}
                  </TableCell>
                  <TableCell><DecisionBadge decision={r.decision} /></TableCell>
                  <TableCell><RiskText risk={r.risk_level} /></TableCell>
                  <TableCell className="tabular-nums">
                    {fmt(current.cpu_request_millicores, 'm')}
                    {proposed && <span className="text-muted-foreground"> <ArrowRight className="inline size-3" aria-label="to" /> {fmt(proposed.cpu_request_millicores, 'm')}</span>}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {fmt(current.memory_request_mib, 'MiB')}
                    {proposed && <span className="text-muted-foreground"> <ArrowRight className="inline size-3" aria-label="to" /> {fmt(proposed.memory_request_mib, 'MiB')}</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {counted > 0 ? (
                      <span className="font-medium text-emerald-600 dark:text-emerald-400">${counted.toFixed(2)}</span>
                    ) : found > 0 ? (
                      <span title={`Found by the optimizer and refused by a safety rule: $${found.toFixed(2)}/mo`}>
                        <span className="text-amber-600 dark:text-amber-400">${found.toFixed(2)}</span>
                        <span className="block text-[10px] text-muted-foreground">held</span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </Card>
  )
}