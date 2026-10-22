import { CalendarClock, FileCode2, LineChart, TriangleAlert, CheckCircle2, Database, type LucideIcon } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { AnalysisResponse } from '@/types'

interface Source { icon: LucideIcon; name: string; value: string; note: string; warn: boolean }

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
  const inEvent = d.results.filter((r) => r.checks.some((c) => c.name === 'event_window' && c.status === 'triggered')).length
  const source = health?.source === 'zetaris' ? 'Zetaris metrics' : health?.source === 'local_fallback' ? 'Local files (remote fell back)' : 'Local files'
  return [
    { icon: FileCode2, name: 'Deployments', value: `${d.results.length} workloads`, note: `${namespaces} namespaces · ${source}`, warn: false },
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
    { icon: CalendarClock, name: 'Business events', value: `${inEvent} in an event window`, note: inEvent ? 'Reductions near events are challenged' : 'No upcoming events affect these workloads', warn: false },
  ]
}

export default function InputStatus({ data }: { data: AnalysisResponse }) {
  const issues = data.input_issues ?? []
  const health = data.data_health
  return (
    <Card>
      <CardHeader>
        <CardTitle>Input status</CardTitle>
        <CardDescription>
          Data sources behind this analysis
          {health && (
            <> · <span className="inline-flex items-center gap-1"><Database className="size-3" aria-hidden />{health.source}</span></>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-3">
        {deriveSources(data).map(({ icon: Icon, name, value, note, warn }) => (
          <div key={name} className="flex gap-3 rounded-lg border bg-background p-3">
            <Icon className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden />
            <div className="min-w-0">
              <p className="flex items-center gap-1.5 text-sm font-medium">
                {name}
                {warn
                  ? <TriangleAlert className="size-3.5 text-amber-500" aria-label="Warning" />
                  : <CheckCircle2 className="size-3.5 text-emerald-500" aria-label="OK" />}
              </p>
              <p className="text-sm">{value}</p>
              <p className="text-xs text-muted-foreground">{note}</p>
            </div>
          </div>
        ))}
        {issues.length > 0 && (
          <ul className="space-y-1 sm:col-span-3" aria-label="Validation issues">
            {issues.map((i) => (
              <li key={`${i.code}-${i.workload_id ?? ''}-${i.message}`} className="flex items-start gap-2 rounded-md border bg-background px-3 py-2 text-sm">
                <TriangleAlert className={i.severity === 'error' ? 'mt-0.5 size-4 shrink-0 text-red-500' : 'mt-0.5 size-4 shrink-0 text-amber-500'} aria-hidden />
                <span><span className="font-medium">{i.code}</span> · {i.message}{i.source ? <span className="text-muted-foreground"> ({i.source})</span> : null}</span>
              </li>
            ))}
          </ul>
        )}
        {health?.workloads.map((workload) => (
          <div key={workload.workload_id} className="rounded-md border bg-background px-3 py-2 text-sm">
            <p className="font-medium">
              {workload.workload_id} <span className={workload.status === 'healthy' ? 'text-emerald-600' : workload.status === 'error' ? 'text-red-600' : 'text-amber-600'}>· {workload.status}</span>
            </p>
            <p className="text-xs text-muted-foreground">
              {workload.sample_count}/{workload.required_samples} samples · {workload.span_hours.toFixed(1)}/{workload.required_span_hours.toFixed(1)} h history
              {workload.latest_metric_age_hours !== null ? ` · latest ${workload.latest_metric_age_hours.toFixed(1)} h ago` : ' · no metrics'}
            </p>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
