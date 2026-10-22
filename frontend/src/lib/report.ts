import type { AnalysisResponse, WorkloadResult } from '@/types'

const label = (d: string) => d.replaceAll('_', ' ')

/**
 * Markdown audit report, built in the browser from the analysis on screen.
 *
 * The backend builds the same document server-side (report_service.py). This is the offline
 * fallback for when the API is unreachable, so it has to carry the same substance: the critic's
 * checks, the agent's objections and confidence, the review cycle and the rollout plan. A report
 * that quietly drops the reasoning is worse than no report, because it looks complete.
 */
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
  if (data.policy_version || data.rule_version) {
    out.push(
      `Policy \`${data.policy_version ?? '—'}\` · rules \`${data.rule_version ?? '—'}\`${data.input_fingerprint ? ` · input \`${data.input_fingerprint}\`` : ''}`,
      '',
    )
  }
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
      // Potential is what the optimizer found, counted is what survived the critic. Reporting only
      // the counted figure would make the safety rules look free.
      `Potential saving $${(w.proposal.estimated_monthly_saving_usd + (w.proposal.suppressed_saving_usd ?? 0)).toFixed(2)} / mo; counted $${w.monthly_savings_estimate_usd.toFixed(2)}${
        w.proposal.suppressed_saving_usd
          ? `; $${w.proposal.suppressed_saving_usd.toFixed(2)} held back by a safety rule`
          : ''
      }.`,
      '',
      '**Critic audit trail**',
      '',
      `- Optimizer: ${label(w.proposal.status)}${w.proposal.reasons.length ? ' — ' + w.proposal.reasons.join('; ') : ''}`,
      ...w.checks.map((k) => `- ${label(k.name)} [${k.code}] ${k.status}: ${k.message}`),
      `- Decision: ${label(w.decision)}`,
      '',
    )
    out.push(...agentSection(w))
    if (w.yaml_patch) out.push('Proposed patch (review-only):', '', '```yaml', w.yaml_patch, '```', '')
  }
  return out.join('\n')
}

/** The agent-only blocks: confidence, objections, review cycle, rollout plan. */
function agentSection(w: WorkloadResult): string[] {
  const out: string[] = []

  if (w.confidence_score != null) {
    out.push(
      '**Agent confidence**',
      '',
      `${w.confidence_score.toFixed(1)}/100${w.confidence_basis ? ` — ${w.confidence_basis}` : ''}`,
      '',
    )
  }

  if (w.objections?.length) {
    out.push(
      '**Adversarial objections**',
      '',
      ...w.objections.map((o) => `- ${o.severity === 'blocking' ? 'BLOCKING' : 'ADVISORY'} · ${o.code}: ${o.message}`),
      '',
    )
  }

  if (w.cycles?.length) {
    out.push('**Review cycle**', '')
    for (const c of w.cycles) {
      out.push(`- **${label(c.role)}**${c.verdict ? ` — ${c.verdict}` : ''}: ${c.summary}`)
      if (c.steps.length) {
        out.push(`  - Tools called: ${c.steps.map((st) => st.tool).join(', ')}`)
      }
      for (const o of c.objections ?? []) out.push(`  - Objection ${o.code} (${o.severity}): ${o.message}`)
    }
    out.push('')
  }

  if (w.historical_lessons?.length) {
    out.push('**Historical lessons (from prior human reviews)**', '', ...w.historical_lessons.map((l) => `- ${l}`), '')
  }

  if (w.evidence_trail?.length) {
    out.push('**Evidence trail**', '', ...w.evidence_trail.map((l) => `- ${l}`), '')
  }

  if (w.rollout_guidance) {
    const g = w.rollout_guidance
    out.push(
      '**Rollout and rollback**',
      '',
      '- Test:',
      ...g.test_steps.map((s) => `  - ${s}`),
      '- Watch:',
      ...g.watch_metrics.map((s) => `  - ${s}`),
      `- Rollback: ${g.rollback}`,
      '',
    )
  }

  return out
}

export function downloadText(filename: string, text: string, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const anchor = Object.assign(document.createElement('a'), { href: url, download: filename })
  anchor.click()
  // Revoking synchronously can cancel the download before the browser has read the blob, so the
  // URL is released a tick later instead.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}