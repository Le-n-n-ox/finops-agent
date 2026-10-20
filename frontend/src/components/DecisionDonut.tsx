import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { DECISIONS } from './DecisionBadge'
import type { AnalysisSummary, DecisionStatus } from '@/types'

const ORDER: DecisionStatus[] = ['approved', 'deferred', 'rejected', 'needs_review', 'no_change']
const FILL: Record<DecisionStatus, string> = {
  approved: '#10b981', deferred: '#f59e0b', rejected: '#ef4444', needs_review: '#6366f1', no_change: '#94a3b8',
}

interface Props { summary: AnalysisSummary; onFilter: (f: DecisionStatus | 'all') => void; active: DecisionStatus | 'all' }

export default function DecisionDonut({ summary, onFilter, active }: Props) {
  const data = ORDER.map((k) => ({ key: k, name: DECISIONS[k].label, value: summary[k] })).filter((d) => d.value > 0)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Decision split</CardTitle>
        <CardDescription>How the Context Critic ruled on each proposal</CardDescription>
      </CardHeader>
      <CardContent className="flex items-center gap-4">
        <div className="relative size-40 shrink-0" role="img" aria-label={`Decisions: ${data.map((d) => `${d.value} ${d.name}`).join(', ')}`}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} dataKey="value" nameKey="name" innerRadius={50} outerRadius={72} paddingAngle={data.length > 1 ? 3 : 0} stroke="none" isAnimationActive>
                {data.map((d) => <Cell key={d.key} fill={FILL[d.key]} />)}
              </Pie>
              <Tooltip contentStyle={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} itemStyle={{ color: 'var(--foreground)' }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-semibold tabular-nums">{summary.workloads_evaluated}</span>
            <span className="text-xs text-muted-foreground">workloads</span>
          </div>
        </div>
        <ul className="min-w-0 flex-1 space-y-1">
          {ORDER.map((k) => (
            <li key={k}>
              <button
                onClick={() => onFilter(active === k ? 'all' : k)}
                aria-pressed={active === k}
                className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-sm outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                <span className="size-2.5 shrink-0 rounded-full" style={{ background: FILL[k] }} aria-hidden />
                <span className="flex-1 truncate">{DECISIONS[k].label}</span>
                <span className="tabular-nums text-muted-foreground">{summary[k]}</span>
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}