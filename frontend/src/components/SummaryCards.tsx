import { PiggyBank } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCountUp } from '@/hooks/useCountUp'
import { DECISIONS } from './DecisionBadge'
import type { AnalysisSummary, DecisionStatus } from '@/types'

const ORDER: DecisionStatus[] = ['approved', 'deferred', 'rejected', 'needs_review', 'no_change']

interface Props {
  summary: AnalysisSummary
  active: DecisionStatus | 'all'
  onFilter: (f: DecisionStatus | 'all') => void
}

const ENTER = 'animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-both motion-reduce:animate-none'

export default function SummaryCards({ summary, active, onFilter }: Props) {
  const savings = useCountUp(summary.estimated_monthly_savings_usd)
  return (
    <section aria-label="Summary" className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      <Card className={cn(ENTER, 'col-span-2 gap-1 py-4 md:col-span-3 lg:col-span-1')}>
        <CardContent>
          <p className="flex items-center gap-1.5 text-xs tracking-wide text-muted-foreground uppercase"><PiggyBank className="size-3.5" aria-hidden />Est. savings / mo</p>
          <p className="mt-1 font-mono text-2xl font-semibold text-primary tabular-nums">${savings.toFixed(2)}</p>
          <p className="text-xs text-muted-foreground">Approved only · illustrative</p>
        </CardContent>
      </Card>
      {ORDER.map((key, i) => {
        const { label, icon: Icon, accent } = DECISIONS[key]
        const selected = active === key
        return (
          <button
            key={key}
            style={{ animationDelay: `${(i + 1) * 60}ms` }}
            onClick={() => onFilter(selected ? 'all' : key)}
            aria-pressed={selected}
            className={cn(
              ENTER,
              'rounded-xl border bg-card p-4 text-left shadow-sm transition outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50',
              selected && 'ring-2 ring-primary',
            )}
          >
            <p className="flex items-center gap-1.5 text-xs tracking-wide text-muted-foreground uppercase"><Icon className={cn('size-3.5', accent)} aria-hidden />{label}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{summary[key]}</p>
          </button>
        )
      })}
    </section>
  )
}