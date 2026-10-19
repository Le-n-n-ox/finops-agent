import { ArrowRight } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { DecisionBadge, RiskText } from './DecisionBadge'
import type { WorkloadResult } from '@/types'

interface Props {
  results: WorkloadResult[]
  selectedId: string | null
  onSelect: (id: string) => void
}

const fmt = (n: number | null | undefined, unit: string) => (n == null ? '—' : `${n.toLocaleString()} ${unit}`)

export default function ResultsTable({ results, selectedId, onSelect }: Props) {
  if (results.length === 0) {
    return <Card className="items-center border-dashed py-10 text-sm text-muted-foreground">No workloads match this filter.</Card>
  }
  return (
    <Card className="gap-0 overflow-hidden py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Workload</TableHead>
            <TableHead>Decision</TableHead>
            <TableHead>Risk</TableHead>
            <TableHead>CPU request</TableHead>
            <TableHead>Memory request</TableHead>
            <TableHead className="text-right">Saving / mo</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {results.map((r) => {
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
    </Card>
  )
}