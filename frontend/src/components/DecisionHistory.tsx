import { useEffect, useMemo, useState } from 'react'
import { Clock, History, Loader2, Search, SearchX, TriangleAlert } from 'lucide-react'
import { fetchDecisions, fetchReportDetail } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { DecisionBadge, RiskText } from './DecisionBadge'
import { cn } from '@/lib/utils'
import type { DecisionRecord, DecisionStatus, ExpiryResult } from '@/types'

/**
 * Every decision the critic has made, across reports.
 *
 * A single analysis is a snapshot; the history is what turns it into a trail. It answers the
 * questions a reviewer asks after the fact: did we recommend the same thing twice, did a human
 * reject it last time, and is this recommendation still valid against the metrics we have now?
 *
 * The expiry column is the one that changes behaviour: a decision whose metrics have moved since
 * it was made is marked stale, and the backend refuses to accept it for implementation.
 */

const STATUSES: DecisionStatus[] = ['approved', 'deferred', 'rejected', 'needs_review', 'no_change']

const ACTION_LABEL: Record<string, string> = {
  ACCEPTED_FOR_IMPLEMENTATION: 'Accepted',
  REJECTED: 'Rejected',
  NEEDS_INVESTIGATION: 'Needs investigation',
}

function DecisionRow({
  record,
  expiry,
  expanded,
  onToggle,
}: {
  record: DecisionRecord
  expiry?: ExpiryResult | null
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <>
      <tr
        className={cn('cursor-pointer border-t align-top hover:bg-muted/40', expanded && 'bg-muted/40')}
        onClick={onToggle}
      >
        <td className="py-2 pr-3">
          <p className="font-medium">{record.workload_id}</p>
          <p className="text-xs text-muted-foreground">{record.namespace}</p>
        </td>
        <td className="py-2 pr-3"><DecisionBadge decision={record.decision} /></td>
        <td className="py-2 pr-3 text-xs text-muted-foreground">risk <RiskText risk={record.risk_level} /></td>
        <td className="py-2 pr-3 tabular-nums">
          {record.latest_action
            ? <span className="text-xs">{ACTION_LABEL[record.latest_action] ?? record.latest_action}</span>
            : <span className="text-xs text-muted-foreground">—</span>}
        </td>
        <td className="py-2 pr-3">
          {expiry?.stale ? (
            <span className="inline-flex items-center gap-1 rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
              <TriangleAlert className="size-3" aria-hidden />Stale
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">Current</span>
          )}
        </td>
        <td className="py-2 pr-3 text-xs whitespace-nowrap text-muted-foreground">
          <Clock className="mr-1 inline size-3" aria-hidden />{new Date(record.created_at).toLocaleString()}
        </td>
      </tr>
      {expanded && (
        <tr className="border-t">
          <td colSpan={6} className="py-3">
            <p className="text-sm">{record.reason}</p>
            <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2">
              <div className="flex gap-1.5"><dt>Policy</dt><dd className="font-mono">{record.policy_version}</dd></div>
              <div className="flex gap-1.5"><dt>Rules</dt><dd className="font-mono">{record.rule_version}</dd></div>
              <div className="flex gap-1.5"><dt>Config</dt><dd className="font-mono break-all">{record.config_hash}</dd></div>
              <div className="flex gap-1.5"><dt>Event version</dt><dd className="font-mono">{record.event_version}</dd></div>
              <div className="flex gap-1.5"><dt>Report</dt><dd className="font-mono break-all">{record.report_id}</dd></div>
              {record.input_fingerprint && (
                <div className="flex gap-1.5"><dt>Inputs</dt><dd className="font-mono break-all">{record.input_fingerprint}</dd></div>
              )}
            </dl>
            {expiry?.stale && (
              <p className="mt-2 flex items-start gap-1.5 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                {expiry.message}{expiry.reasons.length ? ` (${expiry.reasons.join('; ')})` : ''}
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

export default function DecisionHistory() {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<DecisionStatus | 'all'>('all')
  const [records, setRecords] = useState<DecisionRecord[] | null>(null)
  const [expiry, setExpiry] = useState<Record<string, ExpiryResult>>({})
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      setLoading(true)
      const res = await fetchDecisions({ status: status === 'all' ? undefined : status, q: query || undefined })
      if (!alive) return
      setRecords(res.data ?? [])
      setFailed(res.failed)
      setLoading(false)
      if (!res.data?.length) { setExpiry({}); return }
      // One request per report, not per decision: several decisions share a report.
      const reportIds = [...new Set(res.data.map((d) => d.report_id))]
      const details = await Promise.all(reportIds.map((id) => fetchReportDetail(id)))
      const map: Record<string, ExpiryResult> = {}
      for (const detail of details) {
        for (const d of detail.data?.decisions ?? []) {
          if (d.expiry) map[d.record.decision_id] = d.expiry
        }
      }
      if (alive) setExpiry(map)
    }
    void load()
    return () => { alive = false }
  }, [status, query])

  const total = useMemo(() => records?.length ?? 0, [records])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="size-5 text-muted-foreground" aria-hidden />Decision history
        </CardTitle>
        <CardDescription>
          Every decision the critic has made, newest first. A stale decision is one whose metrics
          have moved since it was made; the backend will not accept a stale decision for implementation.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-48">
            <Search className="pointer-events-none absolute top-1/2 left-2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by workload or namespace"
              aria-label="Search decisions"
              className="h-8 w-full rounded-md border bg-background pr-2 pl-8 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />
          </div>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by decision">
            {(['all', ...STATUSES] as const).map((s) => (
              <Button
                key={s}
                size="sm"
                variant={status === s ? 'secondary' : 'ghost'}
                aria-pressed={status === s}
                onClick={() => setStatus(s)}
                className="h-7 capitalize"
              >
                {s === 'all' ? 'All' : s.replaceAll('_', ' ')}
              </Button>
            ))}
          </div>
        </div>

        {loading && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />Loading decisions…
          </p>
        )}

        {!loading && failed && (
          <p role="alert" className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            <TriangleAlert className="size-4 shrink-0" aria-hidden />The decision history could not be loaded.
          </p>
        )}

        {!loading && !failed && total === 0 && (
          <p className="flex flex-col items-center gap-2 rounded-md border border-dashed p-8 text-sm text-muted-foreground">
            <SearchX className="size-6" aria-hidden />
            No decision matches this filter.
          </p>
        )}

        {!loading && total > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Past critic decisions</caption>
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="pb-1 font-medium">Workload</th>
                  <th scope="col" className="pb-1 font-medium">Decision</th>
                  <th scope="col" className="pb-1 font-medium">Risk</th>
                  <th scope="col" className="pb-1 font-medium">Review</th>
                  <th scope="col" className="pb-1 font-medium">Validity</th>
                  <th scope="col" className="pb-1 font-medium">When</th>
                </tr>
              </thead>
              <tbody>
                {records!.map((r) => (
                  <DecisionRow
                    key={r.decision_id}
                    record={r}
                    expiry={expiry[r.decision_id]}
                    expanded={expanded === r.decision_id}
                    onToggle={() => setExpanded((id) => (id === r.decision_id ? null : r.decision_id))}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
