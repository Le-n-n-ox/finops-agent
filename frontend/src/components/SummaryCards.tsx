import { PiggyBank } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useCountUp } from '@/hooks/useCountUp'
import { DECISIONS } from './DecisionBadge'
import type { AnalysisSummary, DecisionStatus } from '@/types'

/** The same order the decision donut draws, so the two never read differently. */
const ORDER: DecisionStatus[] = ['approved', 'deferred', 'needs_review', 'rejected', 'no_change']

interface Props {
  summary: AnalysisSummary
  active: DecisionStatus | 'all'
  onFilter: (f: DecisionStatus | 'all') => void
}

const ENTER = 'app-rise'

export default function SummaryCards({ summary, active, onFilter }: Props) {
  const savings = useCountUp(summary.estimated_monthly_savings_usd)
  return (
    <section aria-label="Summary" className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      <Card
        className={cn(
          ENTER,
          'col-span-2 gap-1 overflow-hidden border-primary/30 bg-primary/5 py-4 md:col-span-3 lg:col-span-1',
        )}
      >
        <CardContent>
          <p className="flex items-center gap-1.5 text-xs tracking-wide text-muted-foreground uppercase">
            <PiggyBank className="size-3.5 text-primary" aria-hidden />
            Est. savings
          </p>
          <p className="mt-1 font-mono text-2xl font-semibold text-primary tabular-nums">
            ${savings.toFixed(2)}
          </p>
          <p className="text-xs text-muted-foreground">Per month · approved only · illustrative</p>
        </CardContent>
      </Card>
      {ORDER.map((key, i) => {
        const { label, icon: Icon, accent, css } = DECISIONS[key]
        const selected = active === key
        return (
          <button
            key={key}
            style={{ animationDelay: `${(i + 1) * 60}ms` }}
            onClick={() => onFilter(selected ? 'all' : key)}
            aria-pressed={selected}
            className={cn(
              ENTER,
              'group relative overflow-hidden rounded-xl border bg-card p-4 text-left shadow-sm transition outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50',
              selected && 'ring-2 ring-primary',
            )}
          >
            {/* The decision's own colour, as a rule along the top of the card. The number and
                the label carry the meaning too, so the colour is never the only cue. */}
            <span
              aria-hidden
              className="absolute inset-x-0 top-0 h-[3px] transition-opacity"
              style={{ background: css, opacity: active === 'all' || selected ? 1 : 0.35 }}
            />
            <p className="flex items-center gap-1.5 text-xs tracking-wide text-muted-foreground uppercase">
              <Icon className={cn('size-3.5', accent)} aria-hidden />
              {label}
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{summary[key]}</p>
          </button>
        )
      })}
    </section>
  )
}
