import { ArrowLeft, ShieldAlert, TrendingDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DECISIONS, DecisionBadge, RiskText } from './DecisionBadge'
import UsageChart from './UsageChart'
import WorkloadDetail from './WorkloadDetail'
import { delta } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DecisionStatus, WorkloadResult } from '@/types'

const CALLOUT: Record<DecisionStatus, string> = {
  approved: 'border-l-emerald-500 bg-emerald-500/10',
  deferred: 'border-l-amber-500 bg-amber-500/10',
  rejected: 'border-l-red-500 bg-red-500/10',
  needs_review: 'border-l-indigo-500 bg-indigo-500/10',
  no_change: 'border-l-slate-400 bg-muted',
}

interface Props {
  result: WorkloadResult
  reportId?: string
  /** Returns to the dashboard. */
  onBack: () => void
  /** Why the what-if cannot run, if it cannot. */
  simulatorUnavailable?: string
}

/** One number with its context, in the row above the charts. */
function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className={cn('mt-1 text-lg font-semibold tabular-nums', tone)}>{value}</p>
      {sub && <p className="text-xs text-muted-foreground tabular-nums">{sub}</p>}
    </div>
  )
}

/**
 * One workload, on its own page.
 *
 * The dashboard's side column was 440px wide, which is enough for a table of numbers and not
 * enough for a chart with a time axis. Here the charts get the width of the window and the
 * analysis sits underneath them, so the evidence behind the decision and the decision itself are
 * read together.
 */
export default function WorkloadPage({ result, reportId, onBack, simulatorUnavailable }: Props) {
  const { proposal: p } = result
  const counted = result.monthly_savings_estimate_usd
  const held = p.suppressed_saving_usd ?? 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2">
          <ArrowLeft aria-hidden />Back to analysis
        </Button>
        {reportId && <span className="text-xs text-muted-foreground">Analysis {reportId}</span>}
      </div>

      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-semibold">{result.workload_id}</h2>
          <DecisionBadge decision={result.decision} />
          <span className="text-sm text-muted-foreground">
            {result.namespace} · risk <RiskText risk={result.risk_level} />
          </span>
        </div>
        <p className={cn('rounded-md border-l-4 p-3 text-sm', CALLOUT[result.decision])}>
          <span className="font-medium">{DECISIONS[result.decision].label}: </span>{result.reason}
        </p>
        {!!held && (
          <p className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
            <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              The optimizer found <span className="font-medium tabular-nums">${held.toFixed(2)}/mo</span> here
              and a safety rule refused it, so the request is unchanged.
              {p.suppressed_proposal && (
                <> It had proposed {p.suppressed_proposal.cpu_request_millicores} m CPU and {p.suppressed_proposal.memory_request_mib} MiB memory.</>
              )}
            </span>
          </p>
        )}
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="CPU request"
          value={`${p.current.cpu_request_millicores ?? '—'} m`}
          sub={p.proposed?.cpu_request_millicores != null ? `proposed ${p.proposed.cpu_request_millicores} m · ${delta(p.current.cpu_request_millicores, p.proposed.cpu_request_millicores)}` : 'no change proposed'}
        />
        <Stat
          label="Memory request"
          value={`${p.current.memory_request_mib ?? '—'} MiB`}
          sub={p.proposed?.memory_request_mib != null ? `proposed ${p.proposed.memory_request_mib} MiB · ${delta(p.current.memory_request_mib, p.proposed.memory_request_mib)}` : 'no change proposed'}
        />
        <Stat
          label="Saving / month"
          value={counted > 0 ? `$${counted.toFixed(2)}` : '—'}
          sub={held > 0 ? `$${held.toFixed(2)} held back by a safety rule` : 'counted for approved decisions only'}
          tone={counted > 0 ? 'text-emerald-600 dark:text-emerald-400' : undefined}
        />
        <Stat
          label="Confidence"
          value={p.confidence ? `${p.confidence.score}/100` : '—'}
          sub={p.confidence?.label ?? 'no proposal confidence scored'}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Usage against the request</CardTitle>
        </CardHeader>
        <CardContent>
          <UsageChart result={result} height="h-64" heading={null} />
        </CardContent>
      </Card>

      <Card data-print-tabs>
        <CardHeader>
          <CardTitle className="text-base">
            <TrendingDown className="mr-1 inline size-4 text-muted-foreground" aria-hidden />
            Analysis
          </CardTitle>
        </CardHeader>
        <CardContent>
          <WorkloadDetail
            result={result}
            reportId={reportId}
            simulatorUnavailable={simulatorUnavailable}
            showUsageChart={false}
          />
        </CardContent>
      </Card>
    </div>
  )
}
