import { useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { TrendPoint } from '@/types'

type View = 'savings' | 'decisions' | 'table'

/**
 * The four decision series, in stack order.
 *
 * The order is not cosmetic: these hues were validated as adjacent pairs for colour-vision
 * deficiency, in this order, against both the light and the dark card surface. Reordering them
 * puts red next to amber and the two collapse for a deuteranopic reader. Re-run the palette
 * check before changing the order or the steps.
 *
 * `no_change` is deliberately absent. It is a neutral, not an identity, and a neutral cannot
 * carry a series colour; it is still reported in the tooltip and in the table.
 */
const SERIES = [
  { key: 'approved', label: 'Approved', color: 'var(--chart-approved)' },
  { key: 'deferred', label: 'Deferred', color: 'var(--chart-deferred)' },
  { key: 'needs_review', label: 'Needs review', color: 'var(--chart-review)' },
  { key: 'rejected', label: 'Rejected', color: 'var(--chart-rejected)' },
] as const

const usd = (v: unknown) => `$${Number(v).toFixed(2)}`
const usdTick = (v: number) => `$${v >= 1000 ? `${(v / 1000).toFixed(1)}K` : v.toFixed(0)}`
const fmtWhen = (t: string) => new Date(t).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

interface Row extends TrendPoint {
  run: number
  /** What the x-axis shows. */
  label: string
  /** The full timestamp, for the tooltip. */
  when: string
  savings: number
  decided: number
  pending: number
}

/** A stacked segment: square on the baseline, 4px rounded on the data-end when it is the top
 *  non-empty segment, and separated from its neighbour by a 2px gap in the surface colour. */
function Segment({ x, y, width, height, fill, payload, above }: any) {
  if (!height || height <= 0) return null
  const rounded = !above.some((k: string) => Number(payload?.[k]) > 0)
  const r = rounded ? 4 : 0
  const d = r === 0
    ? `M ${x} ${y} h ${width} v ${height} h ${-width} Z`
    : `M ${x} ${y + height} L ${x} ${y + r} Q ${x} ${y} ${x + r} ${y} L ${x + width - r} ${y} Q ${x + width} ${y} ${x + width} ${y + r} L ${x + width} ${y + height} Z`
  return <path d={d} fill={fill} stroke="var(--card)" strokeWidth={2} />
}

/** The savings series is one thing, so it gets no legend - the title names it. */
function MoneyTick({ x, y, payload }: any) {
  return (
    <text x={x} y={y} dy={4} textAnchor="end" fill="var(--muted-foreground)" fontSize={10} style={{ fontVariantNumeric: 'tabular-nums' }}>
      {usdTick(payload.value)}
    </text>
  )
}

function CountTick({ x, y, payload }: any) {
  return (
    <text x={x} y={y} dy={4} textAnchor="end" fill="var(--muted-foreground)" fontSize={10} style={{ fontVariantNumeric: 'tabular-nums' }}>
      {payload.value}
    </text>
  )
}

function StatTile({ label, value, delta, tone }: { label: string; value: string; delta?: string; tone?: string }) {
  return (
    <div className="rounded-lg border bg-card px-3 py-2">
      <p className="text-xs tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className="mt-0.5 text-xl font-semibold">{value}</p>
      {delta && <p className={cn('mt-0.5 text-xs', tone ?? 'text-muted-foreground')}>{delta}</p>}
    </div>
  )
}

function TrendTooltip({ active, payload, view }: { active?: boolean; payload?: readonly any[]; view: View }) {
  const row = payload?.[0]?.payload as Row | undefined
  if (!active || !row) return null
  return (
    <div className="pointer-events-none min-w-44 rounded-lg border bg-card/95 p-3 shadow-lg backdrop-blur">
      <p className="text-xs text-muted-foreground">{row.when}</p>
      {view === 'savings' ? (
        <>
          <p className="mt-1 text-lg leading-tight font-semibold">{usd(row.savings)}</p>
          <p className="text-xs text-muted-foreground">Approved savings</p>
          <p className="mt-2 border-t pt-2 text-xs text-muted-foreground">
            {row.approved} approved · {row.deferred} deferred · {row.needs_review} to review · {row.no_change} unchanged
          </p>
        </>
      ) : (
        <>
          <p className="mt-1 text-sm font-medium">{row.decided} decided</p>
          <ul className="mt-1.5 space-y-1">
            {SERIES.map((s) => (
              <li key={s.key} className="flex items-center gap-2 text-xs">
                <span className="h-0.5 w-3 shrink-0 rounded-full" style={{ background: s.color }} aria-hidden />
                <span className="text-muted-foreground">{s.label}</span>
                <span className="ml-auto font-medium tabular-nums">{row[s.key]}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 border-t pt-2 text-xs text-muted-foreground">{row.no_change} unchanged · {usd(row.savings)} approved</p>
        </>
      )}
    </div>
  )
}

/**
 * Savings and decision mix across successive analyses.
 *
 * A single run says what the tool recommends today; the trend says whether the fleet is actually
 * getting cheaper and which decisions are moving.
 *
 * The two measures used to share one plot on two y-axes, which invents a correlation out of an
 * arbitrary alignment of scales. They are separate views here instead: one axis each, one
 * question per view, and a table for the numbers that neither plot can show at once.
 */
export default function TrendChart({ trend }: { trend: TrendPoint[] }) {
  const [view, setView] = useState<View>('savings')

  const data = useMemo<Row[]>(() => {
    const stamps = trend.map((t) => t.generated_at)
    // A fixed demo clock gives every run the same timestamp, so the axis would show the same
    // label twenty times. Fall back to the run number and keep the timestamp in the tooltip.
    const sameStamp = new Set(stamps).size === 1
    const sameDay = new Set(stamps.map((s) => s.slice(0, 10))).size === 1
    return trend.map((t, i) => ({
      ...t,
      run: i + 1,
      label: sameStamp
        ? `Run ${i + 1}`
        : sameDay
          ? new Date(t.generated_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
          : new Date(t.generated_at).toLocaleString(undefined, { month: 'short', day: 'numeric' }),
      when: fmtWhen(t.generated_at),
      savings: t.savings_usd,
      decided: t.approved + t.deferred + t.rejected + t.needs_review,
      pending: t.deferred + t.needs_review,
    }))
  }, [trend])

  const last = data[data.length - 1]
  const prev = data[data.length - 2]
  const average = data.length ? data.reduce((n, d) => n + d.savings, 0) / data.length : 0

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

  const savingsDelta = prev ? last.savings - prev.savings : 0
  const pendingDelta = prev ? last.pending - prev.pending : 0
  const decidedDelta = prev ? last.decided - prev.decided : 0

  const savingsTone = savingsDelta > 0 ? 'text-emerald-600 dark:text-emerald-400' : savingsDelta < 0 ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'
  const pendingTone = pendingDelta > 0 ? 'text-red-600 dark:text-red-400' : pendingDelta < 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'
  const decidedTone = decidedDelta > 0 ? 'text-emerald-600 dark:text-emerald-400' : decidedDelta < 0 ? 'text-muted-foreground' : 'text-muted-foreground'

  const VIEWS: { key: View; label: string }[] = [
    { key: 'savings', label: 'Savings' },
    { key: 'decisions', label: 'Decisions' },
    { key: 'table', label: 'Table' },
  ]

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Trend across analyses</CardTitle>
            <CardDescription>
              {data.length} analyses · {view === 'decisions' ? 'decision counts per run' : 'approved savings per run'}
            </CardDescription>
          </div>
          <div className="flex items-center gap-1 rounded-lg border p-0.5 print:hidden" role="group" aria-label="Trend view">
            {VIEWS.map((v) => (
              <Button
                key={v.key}
                variant={view === v.key ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7"
                aria-pressed={view === v.key}
                onClick={() => setView(v.key)}
              >
                {v.label}
              </Button>
            ))}
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {view === 'savings' && (
          <>
            <div className="mb-3 grid grid-cols-2 gap-2">
              <StatTile label="Approved savings" value={usd(last.savings)} />
              <StatTile
                label="Change since previous run"
                value={`${savingsDelta > 0 ? '+' : savingsDelta < 0 ? '−' : ''}${usd(Math.abs(savingsDelta))}`}
                delta={savingsDelta === 0 ? 'Unchanged since the previous run' : undefined}
                tone={savingsTone}
              />
            </div>
            <div
              className="h-64"
              role="img"
              aria-label={`Approved savings over ${data.length} analyses, from ${usd(data[0].savings)} to ${usd(last.savings)}.`}
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data} margin={{ top: 16, right: 56, left: 0, bottom: 0 }} accessibilityLayer>
                  <defs>
                    <linearGradient id="savingsFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--chart-savings)" stopOpacity={0.14} />
                      <stop offset="100%" stopColor="var(--chart-savings)" stopOpacity={0.01} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    minTickGap={16}
                    interval="preserveStartEnd"
                  />
                  <YAxis tick={<MoneyTick />} axisLine={false} tickLine={false} width={46} />
                  <Tooltip
                    content={<TrendTooltip view={view} />}
                    cursor={{ stroke: 'var(--muted-foreground)', strokeWidth: 1, strokeOpacity: 0.35 }}
                  />
                  <ReferenceLine
                    y={average}
                    stroke="var(--muted-foreground)"
                    strokeOpacity={0.3}
                    strokeWidth={1}
                    label={{ value: `avg ${usd(average)}`, position: 'insideTopLeft', fill: 'var(--muted-foreground)', fontSize: 10 }}
                  />
                  <Area
                    type="monotone"
                    dataKey="savings"
                    name="Approved savings"
                    stroke="var(--chart-savings)"
                    strokeWidth={2}
                    strokeLinecap="round"
                    fill="url(#savingsFill)"
                    activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--card)', fill: 'var(--chart-savings)' }}
                    dot={data.length <= 12 ? { r: 3, strokeWidth: 2, stroke: 'var(--card)', fill: 'var(--chart-savings)' } : false}
                  >
                    <LabelList
                      dataKey="savings"
                      content={({ x, y, index, value }: any) =>
                        index === data.length - 1 ? (
                          <text x={x + 8} y={y + 4} fill="var(--foreground)" fontSize={11} fontWeight={600}>
                            {usd(value)}
                          </text>
                        ) : null
                      }
                    />
                  </Area>
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </>
        )}

        {view === 'decisions' && (
          <>
            <div className="mb-3 grid grid-cols-2 gap-2">
              <StatTile
                label="Decided this run"
                value={String(last.decided)}
                delta={decidedDelta === 0 ? 'Same as the previous run' : `${decidedDelta > 0 ? '+' : '−'}${Math.abs(decidedDelta)} vs previous run`}
                tone={decidedTone}
              />
              <StatTile
                label="Awaiting action"
                value={String(last.pending)}
                delta={pendingDelta === 0 ? 'Same as the previous run' : `${pendingDelta > 0 ? '+' : '−'}${Math.abs(pendingDelta)} vs previous run`}
                tone={pendingTone}
              />
            </div>
            <div
              className="h-64"
              role="img"
              aria-label={`Decisions per analysis over ${data.length} analyses: ${data.map((d) => `${d.label}, ${d.approved} approved, ${d.deferred} deferred, ${d.needs_review} needing review, ${d.rejected} rejected`).join('; ')}`}
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} accessibilityLayer>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    minTickGap={16}
                    interval="preserveStartEnd"
                  />
                  <YAxis tick={<CountTick />} axisLine={false} tickLine={false} width={32} allowDecimals={false} />
                  <Tooltip content={<TrendTooltip view={view} />} cursor={{ fill: 'var(--accent)', fillOpacity: 0.5 }} />
                  {SERIES.map((s, i) => (
                    <Bar
                      key={s.key}
                      dataKey={s.key}
                      name={s.label}
                      stackId="decisions"
                      fill={s.color}
                      maxBarSize={24}
                      shape={(props: any) => <Segment {...props} above={SERIES.slice(i + 1).map((x) => x.key)} />}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {SERIES.map((s) => (
                <li key={s.key} className="flex items-center gap-1.5">
                  <span className="size-2 rounded-full" style={{ background: s.color }} aria-hidden />
                  {s.label}
                </li>
              ))}
            </ul>
          </>
        )}

        {view === 'table' && (
          <div className="max-h-72 overflow-auto rounded-lg border">
            <table className="w-full text-sm">
              <caption className="sr-only">Savings and decisions for each recorded analysis</caption>
              <thead className="sticky top-0 bg-card">
                <tr className="border-b text-left">
                  {['Run', 'When', 'Savings', 'Approved', 'Deferred', 'To review', 'Rejected', 'Unchanged'].map((h, i) => (
                    <th key={h} className="px-3 py-2 text-xs font-medium tracking-wide text-muted-foreground uppercase" style={i >= 2 ? { textAlign: 'right' } : undefined}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.report_id} className="border-b last:border-0">
                    <td className="px-3 py-2 text-muted-foreground">{d.run}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{d.when}</td>
                    <td className="px-3 py-2 text-right font-medium tabular-nums">{usd(d.savings)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{d.approved}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{d.deferred}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{d.needs_review}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{d.rejected}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{d.no_change}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
