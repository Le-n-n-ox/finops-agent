import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { RiskLevel, TopOpportunity } from '@/types'

/** The risk colours are the three state colours, so the page has one risk language. */
const RISK: Record<RiskLevel, string> = {
  low: 'text-positive',
  medium: 'text-caution',
  high: 'text-critical',
}

/**
 * The findings worth acting on first, drawn as bars.
 *
 * The ranking is the optimizer's, and it counts money and confidence together. The bar shows
 * what the ranking is made of: how each finding compares with the biggest one, and how confident
 * the run was about it.
 */
export default function TopOpportunities({ items }: { items: TopOpportunity[] }) {
  if (!items.length) return null
  const max = Math.max(...items.map((i) => i.monthly_savings_usd), 0.01)

  return (
    <Card className="gap-0 py-0">
      <CardContent className="px-5 py-5">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="font-semibold">Top opportunities</h2>
          <p className="text-xs text-muted-foreground">
            Ranked by the optimizer · bar is the monthly saving relative to the largest
          </p>
        </div>

        <ol className="space-y-2.5">
          {items.map((item, index) => (
            <li
              key={item.workload_id}
              className="app-rise grid grid-cols-[1.75rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1"
              style={{ animationDelay: `${index * 70}ms` }}
            >
              <span className="text-sm font-semibold text-muted-foreground tabular-nums">
                {index + 1}
              </span>

              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="truncate text-sm font-medium">{item.workload_id}</span>
                  <span className={cn('text-xs', RISK[item.risk_level])}>{item.risk_level} risk</span>
                </div>
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="app-grow h-full rounded-full bg-primary"
                    style={{ width: `${(item.monthly_savings_usd / max) * 100}%`, animationDelay: `${index * 70 + 120}ms` }}
                  />
                </div>
              </div>

              <div className="text-right">
                <p className="text-sm font-semibold tabular-nums">
                  ${item.monthly_savings_usd.toFixed(2)}
                  <span className="text-xs font-normal text-muted-foreground"> / mo</span>
                </p>
                <p className="text-xs text-muted-foreground tabular-nums">
                  priority {item.priority_score.toFixed(2)} · {Math.round(item.confidence_score)}%
                </p>
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}
