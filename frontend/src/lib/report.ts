import type { AnalysisResponse } from '@/types'

const label = (d: string) => d.replaceAll('_', ' ')

export function buildReport(data: AnalysisResponse): string {
  const s = data.summary
  const out: string[] = [
    '# Kubernetes FinOps Agent — Decision report',
    '',
    `Generated: ${data.generated_at} · Mode: ${data.mode} · Analysis: ${data.analysis_id}`,
    '',
    '> Recommendation-only. Savings are illustrative estimates. Patches are proposals for human review and are never applied automatically.',
    '',
    '## Summary',
    '',
    '| Evaluated | Approved | Deferred | Rejected | Needs review | No change | Est. savings / mo (approved) |',
    '|---|---|---|---|---|---|---|',
    `| ${s.workloads_evaluated} | ${s.approved} | ${s.deferred} | ${s.rejected} | ${s.needs_review} | ${s.no_change} | $${s.estimated_monthly_savings_usd.toFixed(2)} |`,
    '',
  ]
  for (const w of data.results) {
    const { current: c, proposed: p, metrics: m } = w.proposal
    out.push(
      `## ${w.workload_id} (${w.namespace}) — ${label(w.decision)} · risk ${w.risk_level}`,
      '',
      w.reason,
      '',
      '| | Current | Proposed |',
      '|---|---|---|',
      `| CPU request | ${c.cpu_request_millicores ?? '—'} m | ${p?.cpu_request_millicores ?? '—'} m |`,
      `| Memory request | ${c.memory_request_mib ?? '—'} MiB | ${p?.memory_request_mib ?? '—'} MiB |`,
      '',
      `Evidence: ${m.sample_count} samples over ${m.span_hours} h; CPU p95/p99 ${m.cpu_p95 ?? '—'}/${m.cpu_p99 ?? '—'} m; memory p95/p99 ${m.memory_p95 ?? '—'}/${m.memory_p99 ?? '—'} MiB.`,
      `Potential saving $${w.proposal.estimated_monthly_saving_usd.toFixed(2)} / mo; counted $${w.monthly_savings_estimate_usd.toFixed(2)}.`,
      '',
      '**Critic audit trail**',
      '',
      `- Optimizer: ${label(w.proposal.status)}${w.proposal.reasons.length ? ' — ' + w.proposal.reasons.join('; ') : ''}`,
      ...w.checks.map((k) => `- ${label(k.name)} [${k.code}] ${k.status}: ${k.message}`),
      `- Decision: ${label(w.decision)}`,
      '',
    )
    if (w.yaml_patch) out.push('Proposed patch (review-only):', '', '```yaml', w.yaml_patch, '```', '')
  }
  return out.join('\n')
}

export function downloadText(filename: string, text: string, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  Object.assign(document.createElement('a'), { href: url, download: filename }).click()
  URL.revokeObjectURL(url)
}