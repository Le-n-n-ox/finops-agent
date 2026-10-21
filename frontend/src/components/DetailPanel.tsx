import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Check, ClipboardCopy, Download, FileCode2, GitCommitVertical, Info, ListChecks, Lock, TriangleAlert, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CHECK_STYLE, DECISIONS, DecisionBadge, RiskText } from './DecisionBadge'
import ReviewForm from './ReviewForm'
import UsageChart from './UsageChart'
import YamlDiff from './YamlDiff'
import { downloadText } from '@/lib/report'
import { cn } from '@/lib/utils'
import type { DecisionStatus, WorkloadResult } from '@/types'

const CALLOUT: Record<DecisionStatus, string> = {
  approved: 'border-l-emerald-500 bg-emerald-500/10',
  deferred: 'border-l-amber-500 bg-amber-500/10',
  rejected: 'border-l-red-500 bg-red-500/10',
  needs_review: 'border-l-indigo-500 bg-indigo-500/10',
  no_change: 'border-l-slate-400 bg-muted',
}

interface BarProps { label: string; unit: string; request: number | null; proposed?: number | null; p99: number | null }

/** Bar scaled to the current request: fill = observed p99, tick = proposed request. */
function UsageBar({ label, unit, request, proposed, p99 }: BarProps) {
  const [on, setOn] = useState(false)
  useEffect(() => {
    const id = requestAnimationFrame(() => setOn(true))
    return () => cancelAnimationFrame(id)
  }, [])
  if (!request) return null
  const pct = (v: number) => Math.min(100, Math.max(0, (v / request) * 100))
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground tabular-nums">p99 {p99 ?? '—'} / request {request} {unit}</span>
      </div>
      <div className="relative h-2.5 rounded-full bg-muted" role="img" aria-label={`${label}: p99 usage ${p99 ?? 'unknown'} of ${request} ${unit} requested`}>
        {p99 != null && <div className="h-full rounded-full bg-primary/70 transition-[width] duration-700 ease-out motion-reduce:transition-none" style={{ width: `${on ? pct(p99) : 0}%` }} />}
        {proposed != null && <div className="absolute -top-0.5 h-3.5 w-0.5 rounded bg-amber-500 transition-[left] duration-700 ease-out motion-reduce:transition-none" style={{ left: `${on ? pct(proposed) : 0}%` }} title={`Proposed ${proposed} ${unit}`} />}
      </div>
    </div>
  )
}

const delta = (cur: number | null, next: number | null | undefined) =>
  cur && next != null ? `${Math.round(((next - cur) / cur) * 100)}%` : '—'

export default function DetailPanel({ result, reportId, className, onClose }: { result: WorkloadResult; reportId?: string; className?: string; onClose?: () => void }) {
  const [copied, setCopied] = useState(false)
  const { proposal: p } = result

  const copy = async () => {
    if (!result.yaml_patch) return
    try {
      await navigator.clipboard.writeText(result.yaml_patch)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
      toast.success('Patch copied to clipboard')
    } catch {
      toast.error('Could not access the clipboard')
    }
  }
  const download = () => {
    if (!result.yaml_patch) return
    const name = `${result.workload_id}.proposed-patch.yaml`
    downloadText(name, result.yaml_patch, 'text/yaml')
    toast.success(`Saved ${name}`)
  }

  return (
    <Card className={cn('animate-in fade-in slide-in-from-right-4 duration-300 motion-reduce:animate-none lg:sticky lg:top-6', className)}>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-lg">{result.workload_id}</CardTitle>
          <div className="flex items-center gap-1">
            <DecisionBadge decision={result.decision} />
            {onClose && <Button variant="ghost" size="icon" className="-mr-2 size-8" onClick={onClose} aria-label="Close details"><X /></Button>}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">{result.namespace} · {p.proposal_id} · risk <RiskText risk={result.risk_level} /></p>
        <p className={cn('mt-2 rounded-md border-l-4 p-3 text-sm', CALLOUT[result.decision])}>
          <span className="font-medium">{DECISIONS[result.decision].label}: </span>{result.reason}
        </p>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="evidence" key={result.workload_id}>
          <TabsList>
            <TabsTrigger value="evidence"><Info aria-hidden />Evidence</TabsTrigger>
            <TabsTrigger value="critic"><ListChecks aria-hidden />Critic</TabsTrigger>
            <TabsTrigger value="patch"><FileCode2 aria-hidden />Patch</TabsTrigger>
          </TabsList>

          <TabsContent value="evidence" className="space-y-5">
            <UsageChart result={result} />
            <div className="space-y-3">
              <UsageBar label="CPU" unit="m" request={p.current.cpu_request_millicores} proposed={p.proposed?.cpu_request_millicores} p99={p.metrics.cpu_p99} />
              <UsageBar label="Memory" unit="MiB" request={p.current.memory_request_mib} proposed={p.proposed?.memory_request_mib} p99={p.metrics.memory_p99} />
              <p className="text-xs text-muted-foreground"><span className="mr-1 inline-block h-2.5 w-0.5 translate-y-0.5 rounded bg-amber-500" />Proposed request</p>
            </div>
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr><th className="pb-1 font-medium" /><th className="pb-1 font-medium">Current</th><th className="pb-1 font-medium">Proposed</th><th className="pb-1 text-right font-medium">Δ</th></tr></thead>
              <tbody className="tabular-nums">
                <tr className="border-t"><td className="py-2 text-muted-foreground">CPU</td><td>{p.current.cpu_request_millicores ?? '—'} m</td><td>{p.proposed?.cpu_request_millicores != null ? `${p.proposed.cpu_request_millicores} m` : '—'}</td><td className="text-right">{delta(p.current.cpu_request_millicores, p.proposed?.cpu_request_millicores)}</td></tr>
                <tr className="border-t"><td className="py-2 text-muted-foreground">Memory</td><td>{p.current.memory_request_mib ?? '—'} MiB</td><td>{p.proposed?.memory_request_mib != null ? `${p.proposed.memory_request_mib} MiB` : '—'}</td><td className="text-right">{delta(p.current.memory_request_mib, p.proposed?.memory_request_mib)}</td></tr>
              </tbody>
            </table>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Samples / span</dt><dd className="tabular-nums">{p.metrics.sample_count} / {p.metrics.span_hours} h</dd>
              <dt className="text-muted-foreground">CPU p95 / p99</dt><dd className="tabular-nums">{p.metrics.cpu_p95 ?? '—'} / {p.metrics.cpu_p99 ?? '—'} m</dd>
              <dt className="text-muted-foreground">Memory p95 / p99</dt><dd className="tabular-nums">{p.metrics.memory_p95 ?? '—'} / {p.metrics.memory_p99 ?? '—'} MiB</dd>
              <dt className="text-muted-foreground">Limits (context)</dt><dd className="tabular-nums">{p.current.cpu_limit_millicores ?? '—'} m / {p.current.memory_limit_mib ?? '—'} MiB</dd>
            </dl>
            {p.confidence && <p className="text-sm"><span className="font-medium">Confidence:</span> {p.confidence.score}/100 ({p.confidence.label})</p>}
            {result.confidence_score != null && (
              <div className="space-y-1 rounded-md border p-3">
                <p className="text-sm"><span className="font-medium">Agent confidence:</span> {result.confidence_score.toFixed(1)}/100</p>
                {result.confidence_basis && <p className="text-xs text-muted-foreground">{result.confidence_basis}</p>}
              </div>
            )}
            {!!result.objections?.length && (
              <section className="space-y-2 rounded-md border p-3">
                <h3 className="text-sm font-medium">Adversarial review objections</h3>
                {result.objections.map((o) => (
                  <p key={o.code} className="text-sm text-muted-foreground">
                    <span className={cn('font-medium', o.severity === 'blocking' ? 'text-red-600 dark:text-red-400' : 'text-amber-700 dark:text-amber-400')}>
                      {o.severity === 'blocking' ? 'BLOCKING' : 'ADVISORY'} · {o.code}:
                    </span>{' '}
                    {o.message}
                  </p>
                ))}
              </section>
            )}
            {!!result.evidence_trail?.length && (
              <details className="rounded-md border p-3">
                <summary className="cursor-pointer text-sm font-medium">Evidence trail ({result.evidence_trail.length} tool calls)</summary>
                <ol className="mt-2 space-y-1">
                  {result.evidence_trail.map((line, i) => (
                    <li key={i} className="break-words text-xs text-muted-foreground">{line}</li>
                  ))}
                </ol>
              </details>
            )}
            {p.priority_score != null && <p className="text-xs text-muted-foreground">Priority score {p.priority_score.toFixed(2)} (estimated savings × confidence ÷ operational risk)</p>}
            {p.savings_estimate?.pricing_available && <p className="text-xs text-muted-foreground">Illustrative monthly estimate range: ${p.savings_estimate.monthly_savings_low_usd?.toFixed(2) ?? '—'}–${p.savings_estimate.monthly_savings_high_usd?.toFixed(2) ?? '—'}. {p.savings_estimate.assumptions.join(' ')}</p>}
            {!!p.findings?.length && <section className="space-y-2 rounded-md border p-3">
              <h3 className="text-sm font-medium">Capacity and configuration findings</h3>
              {p.findings.map((finding) => <p key={finding.code} className="text-sm text-muted-foreground"><span className="font-medium">{finding.severity.toUpperCase()} · {finding.code}:</span> {finding.message}</p>)}
            </section>}
            {result.rollout_guidance && <section className="space-y-2 rounded-md border p-3">
              <h3 className="text-sm font-medium">Rollout and rollback</h3>
              <p className="text-xs font-medium">Test</p>{result.rollout_guidance.test_steps.map((step) => <p key={step} className="text-xs text-muted-foreground">• {step}</p>)}
              <p className="text-xs font-medium">Watch</p>{result.rollout_guidance.watch_metrics.map((metric) => <p key={metric} className="text-xs text-muted-foreground">• {metric}</p>)}
              <p className="text-xs text-muted-foreground"><span className="font-medium">Rollback:</span> {result.rollout_guidance.rollback}</p>
            </section>}
          </TabsContent>

          <TabsContent value="critic" className="space-y-4">
            <ol className="relative space-y-4 border-l pl-5">
              <li>
                <GitCommitVertical className="absolute -left-[9px] size-[18px] bg-card text-muted-foreground" aria-hidden />
                <p className="text-sm font-medium">Optimizer · {p.status.replaceAll('_', ' ')}</p>
                {p.reasons.map((r) => <p key={r} className="text-sm text-muted-foreground">{r}</p>)}
                {p.warnings.map((w) => <p key={w} className="flex gap-1 text-sm text-amber-700 dark:text-amber-400"><TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />{w}</p>)}
              </li>
              {result.checks.map((c) => (
                <li key={c.name + c.code} className="relative">
                  <span className={cn('absolute -left-[26px] top-1.5 size-2.5 rounded-full ring-4 ring-card', CHECK_STYLE[c.status])} aria-label={c.status} />
                  <p className="text-sm font-medium capitalize">{c.name.replaceAll('_', ' ')} <span className="text-xs font-normal text-muted-foreground normal-case">{c.code} · {c.status}</span></p>
                  <p className="text-sm text-muted-foreground">{c.message}</p>
                </li>
              ))}
              {!!result.objections?.length && (
                <li className="relative">
                  <span className="absolute -left-[26px] top-1.5 size-2.5 rounded-full bg-red-500 ring-4 ring-card" aria-label="objection" />
                  <p className="text-sm font-medium">Adversarial review <span className="text-xs font-normal text-muted-foreground">{result.objections.length} objection(s)</span></p>
                  {result.objections.map((o) => (
                    <p key={o.code} className="text-sm text-muted-foreground">
                      <span className={cn('font-medium', o.severity === 'blocking' ? 'text-red-600 dark:text-red-400' : 'text-amber-700 dark:text-amber-400')}>{o.code}</span>: {o.message}
                    </p>
                  ))}
                </li>
              )}
              <li>
                <GitCommitVertical className="absolute -left-[9px] size-[18px] bg-card text-primary" aria-hidden />
                <p className="flex items-center gap-2 text-sm font-medium">Critic decision <DecisionBadge decision={result.decision} /></p>
                <p className="text-sm text-muted-foreground">{result.reason}</p>
              </li>
            </ol>
            {reportId && (
              <ReviewForm
                reportId={reportId}
                workloadId={result.workload_id}
                canAccept={result.decision === 'approved'}
              />
            )}
          </TabsContent>

          <TabsContent value="patch" className="space-y-3">
            <p className="flex items-start gap-2 rounded-md border bg-muted/50 p-2.5 text-xs text-muted-foreground">
              <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />Proposed patch for human review. It is never applied automatically.
            </p>
            {result.yaml_patch ? (
              <>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" size="sm" onClick={copy}>{copied ? <Check /> : <ClipboardCopy />}{copied ? 'Copied' : 'Copy'}</Button>
                  <Button variant="outline" size="sm" onClick={download}><Download />Download</Button>
                </div>
                <YamlDiff patch={result.yaml_patch} />
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No patch — nothing is proposed for this workload.</p>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}
