// Generates mock fixtures for the UI (deterministic). Run from frontend/:  npm run mock
// Reads ../data/sample_analysis_response.json; writes public/mock/analysis.json + public/mock/scenarios/*.json
// Adds OPTIONAL fields usage_series[] and events[] to each workload (see types.ts).
import fs from 'node:fs'

const SRC = process.argv[2] ?? '../data/sample_analysis_response.json'
const OUT = 'public/mock'
const H = 3600e3
const base = JSON.parse(fs.readFileSync(SRC, 'utf8'))

function rng(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Hourly usage that peaks near p99. `spikeTail` = number of final hours ramped up to `spikePeak` (cpu, mem). */
function series(r, { n = 72, endOffsetH = 0, spikeTail = 0, spikePeak = null } = {}) {
  const rand = rng(r.workload_id.length * 7919 + n)
  const { metrics: m, current: cur } = r.proposal
  const cpuTop = m.cpu_p99 ?? cur.cpu_request_millicores * 0.4
  const memTop = m.memory_p99 ?? cur.memory_request_mib * 0.4
  const end = Date.parse(r.proposal.created_at) - endOffsetH * H
  return Array.from({ length: n }, (_, i) => {
    const wave = 0.5 + 0.5 * Math.sin((i / 24) * 2 * Math.PI)
    const k = 0.68 + 0.3 * wave + 0.02 * rand()
    let cpu = cpuTop * k, mem = memTop * (0.9 + 0.1 * k)
    const fromEnd = n - 1 - i
    if (spikeTail && fromEnd < spikeTail) {
      const f = (spikeTail - fromEnd) / spikeTail
      cpu = cpu + (spikePeak.cpu - cpu) * f
      mem = mem + (spikePeak.mem - mem) * f
    }
    return { t: new Date(end - fromEnd * H).toISOString(), cpu: Math.round(cpu), mem: Math.round(mem) }
  })
}

const eventFor = (r) => ({
  name: 'Black Friday Preview Campaign',
  start_at: new Date(Date.parse(r.proposal.created_at) + 23 * H).toISOString(),
  end_at: new Date(Date.parse(r.proposal.created_at) + 35 * H).toISOString(),
  risk: 'high',
})

function enrich(r) {
  const o = { ...r }
  if (r.workload_id === 'email-worker') o.usage_series = series(r, { n: 10, endOffsetH: 96 })
  else o.usage_series = series(r)
  o.events = r.workload_id === 'checkout-service' ? [eventFor(r)] : []
  return o
}

function summarize(results) {
  const s = { workloads_evaluated: results.length, approved: 0, deferred: 0, rejected: 0, needs_review: 0, no_change: 0, estimated_monthly_savings_usd: 0 }
  for (const r of results) {
    s[r.decision] += 1
    if (r.decision === 'approved') s.estimated_monthly_savings_usd += r.monthly_savings_estimate_usd
  }
  s.estimated_monthly_savings_usd = Math.round(s.estimated_monthly_savings_usd * 100) / 100
  return s
}

const byId = Object.fromEntries(base.results.map((r) => [r.workload_id, enrich(r)]))

// Synthetic "recent usage spike" workload -> rejected
const spikeSrc = JSON.parse(JSON.stringify(byId['payment-api']))
const spike = {
  ...spikeSrc,
  workload_id: 'cart-service',
  namespace: 'commerce',
  decision: 'rejected',
  risk_level: 'high',
  reason: 'Recent usage spike: observed p99 now exceeds the proposed request. Keeping current allocation.',
  confidence_score: 52,
  confidence_basis: '100.0% of reported numbers traced to a tool result; 72/24 samples; fresh metrics; 1 blocking objection(s).',
  objections: [
    {
      code: 'PROPOSED_BELOW_P99',
      severity: 'blocking',
      message: 'Proposed 900 m CPU is below observed p99 (1480 m) after the last-6h spike.',
      source: 'get_workload_metrics',
    },
  ],
  monthly_savings_estimate_usd: 0,
  yaml_patch: null,
  checks: [
    { name: 'metrics_completeness', code: 'OK', status: 'passed', message: '72 hourly samples', evidence: {} },
    { name: 'event_window', code: 'NO_EVENT', status: 'passed', message: 'No event in 48h window', evidence: {} },
    { name: 'resource_floor', code: 'PROPOSED_BELOW_P99', status: 'triggered', message: 'Proposed 900 m CPU is below observed p99 (1480 m) after the last-6h spike.', evidence: { proposed_m: 900, p99_m: 1480 } },
  ],
  proposal: {
    ...spikeSrc.proposal,
    proposal_id: 'PRP-0005',
    workload_id: 'cart-service',
    namespace: 'commerce',
    current: { cpu_request_millicores: 2000, cpu_limit_millicores: 4000, memory_request_mib: 8192, memory_limit_mib: 8192 },
    proposed: { cpu_request_millicores: 900, memory_request_mib: 4096 },
    metrics: { sample_count: 72, span_hours: 71, cpu_p95: 1300, cpu_p99: 1480, memory_p95: 6400, memory_p99: 6900 },
    reasons: ['Averages are well below requests'],
    warnings: ['Short-lived spike in the last 6 hours'],
    estimated_monthly_saving_usd: 31.2,
  },
}
spike.usage_series = series(
  { ...spike, proposal: { ...spike.proposal, metrics: { ...spike.proposal.metrics, cpu_p99: 450, memory_p99: 2600 } } },
  { spikeTail: 6, spikePeak: { cpu: 1480, mem: 6900 } },
)
// The spike workload is derived from payment-api, so it inherits its review cycle. Rewrite it
// rather than shipping a cycle that names a different service: a cycle that talks about
// payment-api while the card is about cart-service is worse than no cycle at all.
spike.cycles = [
  {
    ...spikeSrc.cycles[0],
    summary: 'Pulled 72 hourly samples. Average usage sits far below the request, so the proposal targets p99 x 1.2 — but the last 6 hours climb sharply.',
    steps: spikeSrc.cycles[0].steps.map((st) => ({ ...st, params: { workload_id: 'cart-service' } })),
  },
  {
    ...spikeSrc.cycles[1],
    summary: 'Red-teamed the proposal and found a blocking objection: observed p99 over the last 6 hours is 1480 m CPU, above the 900 m the proposal would request. A reduction now would throttle the service during its busiest hours.',
    objections: [
      {
        code: 'PROPOSED_BELOW_P99',
        severity: 'blocking',
        message: 'Proposed 900 m CPU is below observed p99 (1480 m) after the last-6h spike.',
        source: 'get_workload_metrics',
      },
    ],
    verdict: 'escalate',
    steps: spikeSrc.cycles[1].steps.map((st) => ({ ...st, params: { workload_id: 'cart-service' } })),
  },
  {
    ...spikeSrc.cycles[2],
    summary: 'The objection is blocking and the deterministic critic rejected the change, so the current allocation is kept.',
    objections: [
      {
        code: 'PROPOSED_BELOW_P99',
        severity: 'blocking',
        message: 'Proposed 900 m CPU is below observed p99 (1480 m) after the last-6h spike.',
        source: 'get_workload_metrics',
      },
    ],
    verdict: 'rejected',
    steps: spikeSrc.cycles[2].steps.map((st) => ({ ...st, params: { workload_id: 'cart-service' } })),
  },
]
spike.historical_lessons = []

const SCENARIOS = [
  { id: 'all', label: 'All workloads', description: 'Mixed demo set' },
  { id: 'normal', label: 'Normal demand · low utilization', description: 'Reduction approved', results: [byId['payment-api']] },
  { id: 'event-risk', label: 'High-impact event ahead', description: 'Critic defers the reduction', results: [byId['checkout-service']] },
  { id: 'stale', label: 'Missing / stale metrics', description: 'Marked uncertain', results: [byId['email-worker']] },
  { id: 'spike', label: 'Recent usage spike', description: 'Reduction rejected', results: [spike] },
  { id: 'no-change', label: 'No safe reduction', description: 'Capacity preserved', results: [byId['session-store']] },
]

const ISSUES = {
  'email-worker': { severity: 'warning', code: 'INSUFFICIENT_SAMPLES', message: 'email-worker has 10 usage samples (minimum 24).', source: 'usage_history.csv', workload_id: 'email-worker' },
}

const wrap = (id, results) => ({
  ...base,
  analysis_id: `${base.analysis_id}-${id}`,
  summary: summarize(results),
  results,
  input_issues: results.flatMap((r) => (ISSUES[r.workload_id] ? [ISSUES[r.workload_id]] : [])),
})

fs.mkdirSync(`${OUT}/scenarios`, { recursive: true })
fs.writeFileSync(`${OUT}/analysis.json`, JSON.stringify(wrap('all', Object.values(byId)), null, 2))
for (const s of SCENARIOS.filter((s) => s.results)) {
  fs.writeFileSync(`${OUT}/scenarios/${s.id}.json`, JSON.stringify(wrap(s.id, s.results), null, 2))
}
fs.writeFileSync(`${OUT}/scenarios.json`, JSON.stringify(SCENARIOS.map(({ id, label, description }) => ({ id, label, description })), null, 2))
console.log(`Wrote ${SCENARIOS.length} scenarios to ${OUT}/`)