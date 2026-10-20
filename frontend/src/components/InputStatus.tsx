import { CalendarClock, FileCode2, LineChart, TriangleAlert, CheckCircle2, type LucideIcon } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { AnalysisResponse } from '@/types'

interface Source { icon: LucideIcon; name: string; value: string; note: string; warn: boolean }

/** Derived from the analysis result (the API does not yet report per-file status). */
function deriveSources(d: AnalysisResponse): Source[] {
  const namespaces = new Set(d.results.map((r) => r.namespace)).size
  const samples = d.results.reduce((n, r) => n + r.proposal.metrics.sample_count, 0)
  const weak = d.results.filter(
    (r) => r.proposal.status === 'insufficient_data' || r.checks.some((c) => c.name === 'metrics_completeness' && c.status === 'triggered'),
  ).length
  const inEvent = d.results.filter((r) => r.checks.some((c) => c.name === 'event_window' && c.status === 'triggered')).length
  return [
    { icon: FileCode2, name: 'Deployment YAML', value: `${d.results.length} workloads`, note: `${namespaces} namespaces`, warn: false },
    { icon: LineChart, name: 'Usage CSV', value: `${samples.toLocaleString()} samples`, note: weak ? `${weak} with missing/stale metrics` : 'All workloads have enough data', warn: weak > 0 },
    { icon: CalendarClock, name: 'Events JSON', value: `${inEvent} in an event window`, note: inEvent ? 'Reductions near events are challenged' : 'No upcoming events affect these workloads', warn: false },
  ]
}

export default function InputStatus({ data }: { data: AnalysisResponse }) {
  const issues = data.input_issues ?? []
  return (
    <Card>
      <CardHeader>
        <CardTitle>Input status</CardTitle>
        <CardDescription>Data sources behind this analysis</CardDescription>
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
      </CardContent>
    </Card>
  )
}