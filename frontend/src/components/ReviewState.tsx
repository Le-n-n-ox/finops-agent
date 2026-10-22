import { useEffect, useState } from 'react'
import { History, Loader2, MessageSquareWarning, ShieldCheck, User } from 'lucide-react'
import { fetchDecisions, fetchReportDetail } from '@/api'
import { cn } from '@/lib/utils'
import type { AuditRecord } from '@/types'

/**
 * What a human already decided about this workload.
 *
 * A review that is recorded but never shown back is a review nobody will trust. This panel closes
 * that loop: the action, who made it, when, and the structured reasons — which are exactly what
 * the agent replays as "Historical Lessons" on the next run.
 */

const ACTION_META: Record<string, { label: string; className: string }> = {
  ACCEPTED_FOR_IMPLEMENTATION: { label: 'Accepted', className: 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300' },
  REJECTED: { label: 'Rejected', className: 'border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300' },
  NEEDS_INVESTIGATION: { label: 'Needs investigation', className: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300' },
}

function ReviewRow({ record }: { record: AuditRecord }) {
  const meta = ACTION_META[record.action] ?? { label: record.action, className: 'border-border bg-muted text-muted-foreground' }
  return (
    <li className="space-y-1.5 rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn('rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase', meta.className)}>{meta.label}</span>
        {record.reviewer && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <User className="size-3" aria-hidden />{record.reviewer}
          </span>
        )}
        <span className="text-xs text-muted-foreground">{new Date(record.created_at).toLocaleString()}</span>
        {record.resource && (
          <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{record.resource}</span>
        )}
      </div>
      {!!record.rejection_reasons.length && (
        <ul className="space-y-0.5">
          {record.rejection_reasons.map((r) => (
            <li key={r} className="flex items-start gap-1.5 text-xs">
              <MessageSquareWarning className="mt-0.5 size-3 shrink-0 text-red-500" aria-hidden />
              <span>{r}</span>
            </li>
          ))}
        </ul>
      )}
      {record.reviewer_guidance && (
        <p className="text-xs text-muted-foreground"><span className="font-medium">Guidance:</span> {record.reviewer_guidance}</p>
      )}
      {record.comment && <p className="text-xs text-muted-foreground">{record.comment}</p>}
      <p className="text-[10px] text-muted-foreground">
        {record.action === 'REJECTED'
          ? 'This will be replayed to the agent as a lesson on the next analysis of this workload.'
          : 'Recorded in the append-only review log.'}
      </p>
    </li>
  )
}

export default function ReviewState({ workloadId, reportId, refreshKey = 0 }: { workloadId: string; reportId?: string; refreshKey?: number }) {
  // The result is tagged with the key it belongs to, so a workload switch shows the loading state
  // again instead of the previous workload's records. The refresh key changes when a review is
  // recorded, so the panel re-reads the audit log rather than still saying "nothing reviewed".
  const key = `${workloadId}::${reportId ?? ''}::${refreshKey}`
  const [loaded, setLoaded] = useState<{ key: string; records: AuditRecord[] } | null>(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      // Prefer the report's own audit trail (exact records for this decision); fall back to the
      // decision history endpoint, which also covers reviews from earlier reports.
      let found: AuditRecord[] | null = null
      if (reportId) {
        const detail = await fetchReportDetail(reportId)
        const mine = detail.data?.decisions.find((d) => d.record.workload_id === workloadId)
        // An empty audit is not a result: it means this report has nothing, and we should go
        // looking at the reports that do.
        if (mine?.audit.length) found = mine.audit
      }
      if (found === null) {
        const history = await fetchDecisions({ workloadId })
        if (history.data?.length) {
          // One request per report, not per decision: several decisions can share a report.
          const reportIds = [...new Set(history.data.map((d) => d.report_id))]
          const details = await Promise.all(reportIds.map((id) => fetchReportDetail(id)))
          found = history.data.flatMap((d) => {
            const detail = details.find((x) => x.data?.report.analysis_id === d.report_id)
            return detail?.data?.decisions.find((x) => x.record.decision_id === d.decision_id)?.audit ?? []
          })
        }
      }
      if (alive) setLoaded({ key, records: found ?? [] })
    }
    void load()
    return () => { alive = false }
  }, [workloadId, reportId, key])

  if (loaded?.key !== key) {
    return (
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />Loading review history…
      </p>
    )
  }

  if (!loaded.records.length) {
    return (
      <p className="flex items-start gap-2 rounded-md border border-dashed p-3 text-xs text-muted-foreground">
        <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        No human review recorded for this workload yet.
      </p>
    )
  }

  return (
    <section className="space-y-2" aria-label="Review history">
      <h4 className="flex items-center gap-1.5 text-sm font-medium">
        <History className="size-4 text-muted-foreground" aria-hidden />
        Review history ({loaded.records.length})
      </h4>
      <ul className="space-y-2">
        {loaded.records.map((r) => <ReviewRow key={r.id} record={r} />)}
      </ul>
    </section>
  )
}
