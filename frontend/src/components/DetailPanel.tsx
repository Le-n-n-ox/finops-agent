import { useEffect, useState } from 'react'
import { Check, ClipboardCopy, Download, FileCode2, GitCommitVertical, Info, ListChecks, Lock, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CHECK_STYLE, DecisionBadge, RiskText } from './DecisionBadge'
import { cn } from '@/lib/utils'
import type { WorkloadResult } from '@/types'

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

export default function DetailPanel({ result }: { result: WorkloadResult }) {
  const [copied, setCopied] = useState(false)
  const { proposal: p } = result

  const copy = async () => {
    if (!result.yaml_patch) return
    await navigator.clipboard.writeText(result.yaml_patch)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  const download = () => {
    if (!result.yaml_patch) return
    const url = URL.createObjectURL(new Blob([result.yaml_patch], { type: 'text/yaml' }))
    Object.assign(document.createElement('a'), { href: url, download: `${result.workload_id}.proposed-patch.yaml` }).click()
    URL.revokeObjectURL(url)
  }

  return (
    <Card className="animate-in fade-in slide-in-from-right-4 duration-300 motion-reduce:animate-none lg:sticky lg:top-6">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-lg">{result.workload_id}</CardTitle>
          <DecisionBadge decision={result.decision} />
        </div>
        <p className="text-xs text-muted-foreground">{result.namespace} · {p.proposal_id} · risk <RiskText risk={result.risk_level} /></p>
        <p className="pt-1 text-sm">{result.reason}</p>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="evidence" key={result.workload_id}>
          <TabsList>
            <TabsTrigger value="evidence"><Info aria-hidden />Evidence</TabsTrigger>
            <TabsTrigger value="critic"><ListChecks aria-hidden />Critic</TabsTrigger>
            <TabsTrigger value="patch"><FileCode2 aria-hidden />Patch</TabsTrigger>
          </TabsList>

          <TabsContent value="evidence" className="space-y-5">
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
          </TabsContent>

          <TabsContent value="critic">
            <ol className="relative space-y-4 border-l pl-5">
              <li>
                <GitCommitVertical className="absolute -left-[9px] size-[18px] bg-card text-muted-foreground" aria-hidden />
                <p className="text-sm font-medium">Optimizer · {p.status.replaceAll('_', ' ')}</p>
                {p.reasons.map((r) => <p key={r} className="text-sm text-muted-foreground">{r}</p>)}
                {p.warnings.map((w) => <p key={w} className="flex gap-1 text-sm text-amber-600 dark:text-amber-400"><TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />{w}</p>)}
              </li>
              {result.checks.map((c) => (
                <li key={c.name + c.code} className="relative">
                  <span className={cn('absolute -left-[26px] top-1.5 size-2.5 rounded-full ring-4 ring-card', CHECK_STYLE[c.status])} aria-label={c.status} />
                  <p className="text-sm font-medium capitalize">{c.name.replaceAll('_', ' ')} <span className="text-xs font-normal text-muted-foreground normal-case">{c.code} · {c.status}</span></p>
                  <p className="text-sm text-muted-foreground">{c.message}</p>
                </li>
              ))}
              <li>
                <GitCommitVertical className="absolute -left-[9px] size-[18px] bg-card text-primary" aria-hidden />
                <p className="flex items-center gap-2 text-sm font-medium">Critic decision <DecisionBadge decision={result.decision} /></p>
                <p className="text-sm text-muted-foreground">{result.reason}</p>
              </li>
            </ol>
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
                <pre className="max-h-72 overflow-auto rounded-md border bg-muted p-3 text-xs">{result.yaml_patch}</pre>
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