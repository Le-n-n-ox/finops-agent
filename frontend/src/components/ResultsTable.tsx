import { useMemo, useState } from 'react'
import { ArrowDown, ArrowRight, ArrowUp, ArrowUpDown, Search } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DecisionBadge, RiskText } from './DecisionBadge'
import type { RiskLevel, WorkloadResult } from '@/types'

interface Props {
  results: WorkloadResult[]
  selectedId: string | null
  onSelect: (id: string) => void
}

type SortKey = 'workload' | 'risk' | 'saving'
const RISK_RANK: Record<RiskLevel, number> = { low: 0, medium: 1, high: 2 }
const fmt = (n: number | null | undefined, unit: string) => (n == null ? '—' : `${n.toLocaleString()} ${unit}`)

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

export default function ResultsTable({ results, selectedId, onSelect }: Props) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 } | null>(null)

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = q ? results.filter((r) => `${r.workload_id} ${r.namespace}`.toLowerCase().includes(q)) : results
    if (!sort) return filtered
    const val = (r: WorkloadResult) =>
      sort.key === 'workload' ? r.workload_id : sort.key === 'risk' ? RISK_RANK[r.risk_level] : r.monthly_savings_estimate_usd
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
        <p className="p-10 text-center text-sm text-muted-foreground">No workloads match.</p>
      ) : (
        <Table>
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
              return (
                <TableRow
                  key={r.workload_id}
                  tabIndex={0}
                  data-state={selectedId === r.workload_id ? 'selected' : undefined}
                  onClick={() => onSelect(r.workload_id)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(r.workload_id) } }}
                  className="cursor-pointer outline-none focus-visible:bg-muted"
                >
                  <TableCell>
                    <p className="font-medium">{r.workload_id}</p>
                    <p className="text-xs text-muted-foreground">{r.namespace}</p>
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
                  <TableCell className="text-right tabular-nums">${r.monthly_savings_estimate_usd.toFixed(2)}</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </Card>
  )
}