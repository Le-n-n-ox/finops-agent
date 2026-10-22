import {
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  Database,
  FileCode2,
  LineChart,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { AnalysisResponse, WorkloadDataHealth } from '@/types'

interface Source {
  icon: LucideIcon
  name: string
  value: string
  note: string
  warn: boolean
}

/** How each data-health state is drawn. The colour is a status, so it always comes with a label. */
const HEALTH: Record<string, { label: string; color: string; text: string }> = {
  healthy: { label: 'Enough data', color: 'var(--state-positive)', text: 'text-positive' },
  warning: { label: 'Thin or stale', color: 'var(--state-caution)', text: 'text-caution' },
  error: { label: 'Missing', color: 'var(--state-critical)', text: 'text-critical' },
}

/**
 * What the analysis was actually built from.
 *
 * The counts come from the analysis itself and from the validation pass the backend attaches
 * (`data_health`), not from hard-coded file names: the same code runs against a remote metrics
 * source, where there is no CSV on disk. So the source is named from the data and the health
 * figures are the ones the validator reported.
 */
function deriveSources(d: AnalysisResponse): Source[] {
  const namespaces = new Set(d.results.map((r) => r.namespace)).size
  const samples = d.results.reduce((n, r) => n + r.proposal.metrics.sample_count, 0)
  const health = d.data_health
  const unhealthy = health?.workloads.filter((w) => w.status !== 'healthy').length ?? 0
  const inEvent = d.results.filter((r) =>
    r.checks.some((c) => c.name === 'event_window' && c.status === 'triggered'),
  ).length
  const source =
    health?.source === 'zetaris'
      ? 'Zetaris metrics'
      : health?.source === 'local_fallback'
        ? 'Local files (remote fell back)'
        : 'Local files'
  return [
    {
      icon: FileCode2,
      name: 'Deployments',
      value: `${d.results.length} workloads`,
      note: `${namespaces} namespaces · ${source}`,
      warn: false,
    },
    {
      icon: LineChart,
      name: 'Usage metrics',
      value: `${samples.toLocaleString()} samples`,
      note: health
        ? unhealthy
          ? `${unhealthy} of ${health.workloads_checked} workloads have missing, sparse or stale metrics`
          : `All ${health.workloads_checked} workloads have enough data`
        : 'No validation report attached to this run',
      warn: unhealthy > 0,
    },
    {
      icon: CalendarClock,
      name: 'Business events',
      value: `${inEvent} in an event window`,
      note: inEvent
        ? 'Reductions near events are challenged'
        : 'No upcoming events affect these workloads',
      warn: false,
    },
  ]
}

/**
 * The health of the data the run was built on, as one bar.
 *
 * Twelve near-identical rows of text is a wall, and the reader only needs the shape of it: are
 * these numbers good enough to act on? The per-workload detail is still there, one click away.
 */
function HealthMeter({ workloads }: { workloads: WorkloadDataHealth[] }) {
  const counts = new Map<string, number>()
  for (const w of workloads) counts.set(w.status, (counts.get(w.status) ?? 0) + 1)
  const order = ['healthy', 'warning', 'error']
  const present = order.filter((s) => (counts.get(s) ?? 0) > 0)
  const total = workloads.length

  if (!total) return null

  return (
    <div className="rounded-xl border bg-background p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium">Data quality</p>
        <p className="text-xs text-muted-foreground">
          {counts.get('healthy') ?? 0} of {total} workloads have enough history to act on
        </p>
      </div>

      <div
        className="mt-3 flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full bg-muted"
        role="img"
        aria-label={present.map((s) => `${counts.get(s)} ${HEALTH[s].label.toLowerCase()}`).join(', ')}
      >
        {present.map((s, i) => (
          <div
            key={s}
            className="app-grow h-full rounded-full"
            style={{ width: `${((counts.get(s) ?? 0) / total) * 100}%`, background: HEALTH[s].color, animationDelay: `${i * 90}ms` }}
          />
        ))}
      </div>

      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
        {present.map((s) => (
          <li key={s} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="size-2 shrink-0 rounded-full"
              style={{ background: HEALTH[s].color }}
            />
            <span className="text-muted-foreground">{HEALTH[s].label}</span>
            <span className="font-medium tabular-nums">{counts.get(s)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function InputStatus({ data }: { data: AnalysisResponse }) {
  const issues = data.input_issues ?? []
  const health = data.data_health
  const workloads = health?.workloads ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle>Input status</CardTitle>
        <CardDescription>
          Data sources behind this analysis
          {health && (
            <>
              {' '}
              ·{' '}
              <span className="inline-flex items-center gap-1">
                <Database className="size-3" aria-hidden />
                {health.source}
              </span>
            </>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          {deriveSources(data).map(({ icon: Icon, name, value, note, warn }, i) => (
            <div
              key={name}
              className="app-rise flex gap-3 rounded-xl border bg-background p-4 transition-colors hover:border-primary/40"
              style={{ animationDelay: `${i * 70}ms` }}
            >
              <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Icon className="size-4" aria-hidden />
              </span>
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 text-sm font-medium">
                  {name}
                  {warn ? (
                    <TriangleAlert className="size-3.5 text-caution" aria-label="Warning" />
                  ) : (
                    <CheckCircle2 className="size-3.5 text-positive" aria-label="OK" />
                  )}
                </p>
                <p className="text-sm font-medium tabular-nums">{value}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{note}</p>
              </div>
            </div>
          ))}
        </div>

        {workloads.length > 0 && <HealthMeter workloads={workloads} />}

        {issues.length > 0 && (
          <ul className="space-y-1" aria-label="Validation issues">
            {issues.map((i) => (
              <li
                key={`${i.code}-${i.workload_id ?? ''}-${i.message}`}
                className="flex items-start gap-2 rounded-md border bg-background px-3 py-2 text-sm"
              >
                <TriangleAlert
                  className={cn(
                    'mt-0.5 size-4 shrink-0',
                    i.severity === 'error' ? 'text-critical' : 'text-caution',
                  )}
                  aria-hidden
                />
                <span>
                  <span className="font-medium">{i.code}</span> · {i.message}
                  {i.source ? <span className="text-muted-foreground"> ({i.source})</span> : null}
                </span>
              </li>
            ))}
          </ul>
        )}

        {workloads.length > 0 && (
          <details className="group rounded-xl border bg-background">
            <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
              <ChevronRight
                className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90"
                aria-hidden
              />
              Per-workload history
              <span className="text-xs font-normal text-muted-foreground">
                {workloads.length} workloads · samples, span and age
              </span>
            </summary>
            <ul className="grid gap-2 border-t p-3 sm:grid-cols-2 xl:grid-cols-3">
              {workloads.map((workload) => {
                const tone = HEALTH[workload.status] ?? HEALTH.warning
                return (
                  <li
                    key={workload.workload_id}
                    className="rounded-lg border bg-card px-3 py-2 text-sm"
                  >
                    <p className="flex items-center gap-1.5 font-medium">
                      <span className="truncate">{workload.workload_id}</span>
                      <span className={cn('shrink-0 text-xs', tone.text)}>· {tone.label}</span>
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground tabular-nums">
                      {workload.sample_count}/{workload.required_samples} samples ·{' '}
                      {workload.span_hours.toFixed(1)}/{workload.required_span_hours.toFixed(1)} h history
                      {workload.latest_metric_age_hours !== null
                        ? ` · latest ${workload.latest_metric_age_hours.toFixed(1)} h ago`
                        : ' · no metrics'}
                    </p>
                  </li>
                )
              })}
            </ul>
          </details>
        )}
      </CardContent>
    </Card>
  )
}
