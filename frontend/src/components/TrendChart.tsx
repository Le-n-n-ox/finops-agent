import { useMemo } from 'react'
import { Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { DECISIONS } from './DecisionBadge'
import type { DecisionStatus, TrendPoint } from '@/types'

const usd = (v: unknown) => `$${Number(v).toFixed(2)}`
const fmtWhen = (t: string) => new Date(t).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

/**
 * Savings and decision mix across successive analyses.
 *
 * A single run says what the tool recommends today; the trend says whether the fleet is actually
 * getting cheaper and which decisions are moving. The bars are the approved savings; the lines
 * track the other outcomes so a growing "deferred" count is visible as a problem, not a footnote.
 */
export default function TrendChart({ trend }: { trend: TrendPoint[] }) {
  const data = useMemo(
    () => trend.map((t) => ({
      ...t,
      label: fmtWhen(t.generated_at),
      approvedSavings: t.savings_usd,
    })),
    [trend],
  )

  if (data.length < 2) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Trend across analyses</CardTitle>
          <CardDescription>Savings and decision mix over successive runs</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            {data.length === 0
              ? 'No analysis history yet. Run the analysis again to start the trend.'
              : 'One analysis recorded. Run it a second time to see the trend.'}
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Trend across analyses</CardTitle>
        <CardDescription>
          {data.length} analyses · approved savings on the left axis, decision counts on the right
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div
          className="h-52"
          role="img"
          aria-label={`Savings and decisions over ${data.length} analyses: ${data.map((d) => `${d.label}, $${d.approvedSavings.toFixed(2)} approved, ${d.approved} approved, ${d.deferred} deferred, ${d.needs_review} needing review`).join('; ')}`}
        >
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
              <defs>
                <linearGradient id="savingsFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="var(--primary)" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={16} />
              <YAxis yAxisId="usd" tickFormatter={usd} tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }} axisLine={false} tickLine={false} width={56} />
              <YAxis yAxisId="count" orientation="right" tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }} axisLine={false} tickLine={false} width={28} allowDecimals={false} />
              <Tooltip
                contentStyle={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                itemStyle={{ color: 'var(--foreground)' }}
                labelStyle={{ color: 'var(--foreground)' }}
                formatter={(value, name) => [name === 'Approved savings' ? usd(value) : value, name ?? '']}
              />
              <Area yAxisId="usd" type="monotone" dataKey="approvedSavings" name="Approved savings" stroke="var(--primary)" strokeWidth={2} fill="url(#savingsFill)" />
              <Line yAxisId="count" type="monotone" dataKey="deferred" name="Deferred" stroke="var(--muted-foreground)" strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
              <Line yAxisId="count" type="monotone" dataKey="needs_review" name="Needs review" stroke="#6366f1" strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {(['approved', 'deferred', 'needs_review'] as DecisionStatus[]).map((k) => (
            <li key={k} className="flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: DECISIONS[k].hex }} aria-hidden />
              {DECISIONS[k].label}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
