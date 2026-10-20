import { useMemo, useState } from 'react'
import { CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Button } from '@/components/ui/button'
import type { WorkloadResult } from '@/types'

const fmtTick = (t: number) => new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', hour: '2-digit' }).format(t)

/** Usage over time vs current request, proposed request and p99, with business-event windows shaded. */
export default function UsageChart({ result }: { result: WorkloadResult }) {
  const [metric, setMetric] = useState<'cpu' | 'mem'>('cpu')
  const { proposal: p } = result
  const series = result.usage_series
  const events = useMemo(() => result.events ?? [], [result.events])

  const view = useMemo(() => {
    if (!series?.length) return null
    const data = series.map((s) => ({ t: Date.parse(s.t), v: metric === 'cpu' ? s.cpu : s.mem }))
    const now = Date.parse(p.created_at)
    const maxT = Math.max(data[data.length - 1].t, now, ...events.map((e) => Date.parse(e.end_at)))
    return { data, now, domain: [data[0].t, maxT] as [number, number] }
  }, [series, events, metric, p.created_at])

  if (!view) return <p className="text-sm text-muted-foreground">No usage series in this analysis.</p>

  const unit = metric === 'cpu' ? 'm' : 'MiB'
  const request = metric === 'cpu' ? p.current.cpu_request_millicores : p.current.memory_request_mib
  const proposed = metric === 'cpu' ? p.proposed?.cpu_request_millicores : p.proposed?.memory_request_mib
  const p99 = metric === 'cpu' ? p.metrics.cpu_p99 : p.metrics.memory_p99
  const peak = Math.max(...view.data.map((d) => d.v), request ?? 0)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Usage over time</h3>
        <div className="flex gap-1" role="group" aria-label="Metric">
          {(['cpu', 'mem'] as const).map((m) => (
            <Button key={m} size="sm" variant={metric === m ? 'default' : 'outline'} aria-pressed={metric === m} onClick={() => setMetric(m)} className="h-7 px-2">
              {m === 'cpu' ? 'CPU' : 'Memory'}
            </Button>
          ))}
        </div>
      </div>
      <div className="h-48" role="img" aria-label={`${metric === 'cpu' ? 'CPU' : 'Memory'} usage over time against request ${request ?? 'unknown'} ${unit}${proposed != null ? ` and proposed ${proposed} ${unit}` : ''}${events.length ? `, with ${events.map((e) => e.name).join(', ')} shaded` : ''}`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={view.data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis type="number" dataKey="t" scale="time" domain={view.domain} tickFormatter={fmtTick} tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }} tickCount={4} axisLine={false} tickLine={false} />
            <YAxis domain={[0, Math.ceil((peak * 1.1) / 100) * 100]} tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }} axisLine={false} tickLine={false} />
            {events.map((e) => (
              <ReferenceArea key={e.name} x1={Date.parse(e.start_at)} x2={Date.parse(e.end_at)} fill="#f59e0b" fillOpacity={0.18} stroke="#f59e0b" strokeDasharray="3 3" label={{ value: e.name, position: 'insideTop', fill: 'var(--foreground)', fontSize: 10 }} />
            ))}
            <ReferenceLine x={view.now} stroke="var(--muted-foreground)" strokeDasharray="2 4" label={{ value: 'now', position: 'insideTopLeft', fill: 'var(--muted-foreground)', fontSize: 10 }} />
            {request != null && <ReferenceLine y={request} stroke="var(--foreground)" strokeDasharray="6 3" label={{ value: `request ${request}`, position: 'insideTopRight', fill: 'var(--muted-foreground)', fontSize: 10 }} />}
            {p99 != null && <ReferenceLine y={p99} stroke="var(--primary)" strokeDasharray="2 3" label={{ value: `p99 ${p99}`, position: 'insideBottomRight', fill: 'var(--primary)', fontSize: 10 }} />}
            {proposed != null && <ReferenceLine y={proposed} stroke="#f59e0b" strokeWidth={2} label={{ value: `proposed ${proposed}`, position: 'insideBottomLeft', fill: '#d97706', fontSize: 10 }} />}
            <Tooltip labelFormatter={(t) => fmtTick(Number(t))} formatter={(v: unknown) => [`${v} ${unit}`, metric === 'cpu' ? 'CPU' : 'Memory']} contentStyle={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} itemStyle={{ color: 'var(--foreground)' }} labelStyle={{ color: 'var(--foreground)' }} />
            <Line type="monotone" dataKey="v" stroke="var(--primary)" strokeWidth={2} dot={false} isAnimationActive />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}