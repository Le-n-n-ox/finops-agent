import {
  Calculator,
  ChevronRight,
  Database,
  FileText,
  Gavel,
  Scale,
  Search,
  ShieldAlert,
  ShieldQuestion,
  Terminal,
  type LucideIcon,
} from 'lucide-react'
import { Reveal } from '../motion'
import { WasteGapChart } from '../graphics'
import { Section } from './Section'

/* ------------------------------------------------------------------ the problem */

export function Problem() {
  return (
    <Section
      id="problem"
      eyebrow="The problem"
      title="Requests are sized for the worst day, and then never revisited."
      lede="A request written during a traffic spike keeps reserving that headroom for the life of the deployment. The bill pays for the request, not for the work. The agent reads the whole history instead — the 95th and 99th percentiles, the trend, the anomalies — and proposes a request that still clears the safety floor."
    >
      <Reveal className="lp-viz">
        <div className="overflow-hidden rounded-2xl border bg-card shadow-sm">
          <div className="border-b px-6 py-4">
            <h3 className="text-sm font-semibold">One workload, thirty days</h3>
            <p className="text-sm text-muted-foreground">
              Usage against a request that has not moved since it was written.
            </p>
          </div>
          <div className="px-2 py-6 sm:px-6">
            <WasteGapChart className="mx-auto max-w-4xl" />
          </div>
          <div className="grid gap-px border-t bg-border sm:grid-cols-3">
            {[
              { k: 'Request', v: '800 m', d: 'set once, at the busiest week' },
              { k: 'P99 usage', v: '210 m', d: 'what the workload actually needs' },
              { k: 'Headroom', v: '3.8×', d: 'reserved on every replica, every hour' },
            ].map((s) => (
              <div key={s.k} className="bg-card px-6 py-4">
                <p className="text-xs tracking-wide text-muted-foreground uppercase">{s.k}</p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">{s.v}</p>
                <p className="mt-1 text-sm text-muted-foreground">{s.d}</p>
              </div>
            ))}
          </div>
        </div>
      </Reveal>
    </Section>
  )
}

/* ------------------------------------------------------------------ the pipeline */

const STAGES: { icon: LucideIcon; title: string; agent: string; body: string; stat: string }[] = [
  {
    icon: Database,
    title: 'Collect data',
    agent: 'Data Collector',
    body: 'Deployments, usage history, business events, incident history, the safety policy and the cost model.',
    stat: '12 workloads · 8,640 samples',
  },
  {
    icon: Calculator,
    title: 'Estimate waste',
    agent: 'FinOps Optimizer',
    body: 'Percentiles, a candidate request, and the eligibility rules that decide whether a reduction is even allowed.',
    stat: '6 proposals',
  },
  {
    icon: ShieldAlert,
    title: 'Critique risk',
    agent: 'Context Critic',
    body: 'P99 safety floors, business events, incident history, minimum savings and change windows — checked independently.',
    stat: '8 challenged',
  },
  {
    icon: Scale,
    title: 'Decide',
    agent: 'Approve · defer · reject',
    body: 'One critic owns every final status. Requests are never increased, and limits are never touched.',
    stat: '12 decisions',
  },
  {
    icon: FileText,
    title: 'Report',
    agent: 'Report Generator',
    body: 'An audit report and a review-only YAML patch for the approved recommendations.',
    stat: '4 patches',
  },
]

export function Pipeline() {
  return (
    <Section
      id="pipeline"
      eyebrow="The pipeline"
      title="One deterministic path, five stages."
      lede="The same path runs in both modes, so the numbers on screen always come from the same rules. What changes in agent mode is the reasoning around the decision, never the decision itself."
    >
      <div className="lp-viz relative pt-9">
        {/* The rail the stages hang from: a dashed rule travelling to the right, so the row
            reads as a path rather than five separate boxes. */}
        <div aria-hidden className="lp-rail lp-flow absolute inset-x-0 top-0 h-px" />

        <ol className="grid gap-5 sm:grid-cols-2 lg:grid-cols-5">
          {STAGES.map(({ icon: Icon, title, agent, body, stat }, i) => (
            <Reveal key={title} delay={i * 90} className="h-full">
              <li className="group relative flex h-full list-none flex-col rounded-xl border bg-card p-5 shadow-sm transition-shadow hover:shadow-md">
                <div className="flex items-center gap-3">
                  <span className="relative flex size-11 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <span
                      aria-hidden
                      className="absolute inset-0 rounded-lg ring-1 ring-primary/25 transition-all group-hover:ring-primary/50"
                    />
                    <Icon className="size-5" aria-hidden />
                  </span>
                  <span className="text-xs font-semibold text-muted-foreground tabular-nums">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                </div>
                <h3 className="mt-4 font-semibold">{title}</h3>
                <p className="mt-0.5 text-xs text-primary">{agent}</p>
                <p className="mt-3 mb-4 text-sm leading-relaxed text-muted-foreground">{body}</p>
                <p className="mt-auto border-t pt-3 text-xs font-medium text-muted-foreground tabular-nums">
                  {stat}
                </p>
                {i < STAGES.length - 1 && (
                  <span
                    aria-hidden
                    className="absolute top-1/2 -right-3 hidden size-6 -translate-y-1/2 items-center justify-center rounded-full border bg-card text-muted-foreground lg:flex"
                  >
                    <ChevronRight className="size-3.5" />
                  </span>
                )}
              </li>
            </Reveal>
          ))}
        </ol>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ the review cycle */

const PHASES: { role: string; icon: LucideIcon; bound: string; body: string }[] = [
  {
    role: 'Proposer',
    icon: Search,
    bound: '10 iterations',
    body: 'Gathers evidence with tools and argues for or against a reduction — including against itself.',
  },
  {
    role: 'Critic',
    icon: ShieldQuestion,
    bound: '4 iterations',
    body: 'Red-teams the proposal. It may call read-only tools, so every objection is grounded in something it retrieved.',
  },
  {
    role: 'Judge',
    icon: Gavel,
    bound: '3 iterations',
    body: 'Weighs the objections against the deterministic verdict and rules on whether the finding survives.',
  },
]

const OBJECTIONS = [
  'RECURRING_EVENT_UNMODELLED',
  'INCIDENT_OVERLAP_IGNORED',
  'LOG_PRESSURE_IGNORED',
  'DEPENDENCY_PRESSURE_IGNORED',
  'VERIFICATION_GAP',
  'THIN_EVIDENCE',
]

export function AgentCycle() {
  return (
    <Section
      id="cycle"
      eyebrow="The review cycle"
      title="The same decision, argued harder."
      lede="In agent mode the decision path is wrapped in a bounded Proposer → Critic → Judge cycle. It adds red-team objections, an evidence trail and a confidence score. It cannot change a single decision."
      tone="tinted"
    >
      <div className="grid gap-5 lg:grid-cols-3">
        {PHASES.map(({ role, icon: Icon, bound, body }, i) => (
          <Reveal key={role} delay={i * 110}>
            <article className="relative h-full rounded-2xl border bg-card p-6 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Icon className="size-5" aria-hidden />
                </span>
                <span className="rounded-full border px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
                  {bound}
                </span>
              </div>
              <h3 className="mt-5 text-lg font-semibold">{role}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
              {i < PHASES.length - 1 && (
                <span
                  aria-hidden
                  className="absolute top-1/2 -right-3 hidden size-6 -translate-y-1/2 items-center justify-center rounded-full border bg-card text-muted-foreground lg:flex"
                >
                  <ChevronRight className="size-3.5" />
                </span>
              )}
            </article>
          </Reveal>
        ))}
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <Reveal delay={80}>
          <div className="h-full rounded-2xl border bg-card p-6 shadow-sm">
            <h3 className="flex items-center gap-2 font-semibold">
              <Terminal className="size-4 text-primary" aria-hidden />
              Two tools beyond the workload metrics
            </h3>
            <dl className="mt-4 space-y-4">
              <div>
                <dt className="font-mono text-sm font-medium">search_logs</dt>
                <dd className="mt-1 text-sm text-muted-foreground">
                  Simulated container logs for a workload, including OOMKilled, CPU throttling and eviction
                  entries. A log that reports memory pressure raises a blocking objection against reducing
                  the memory request.
                </dd>
              </div>
              <div>
                <dt className="font-mono text-sm font-medium">get_dependencies</dt>
                <dd className="mt-1 text-sm text-muted-foreground">
                  Maps the upstream services a workload depends on, so an incident on a dependency is
                  visible rather than a surprise.
                </dd>
              </div>
            </dl>
            <p className="mt-5 rounded-lg border bg-muted/40 p-3 text-sm leading-relaxed text-muted-foreground">
              Every call an agent makes is written to the evidence trail, and the trail is shown on the
              workload's card and in the Markdown report — so a reviewer can see what was actually
              read, not only what was concluded.
            </p>
          </div>
        </Reveal>

        <Reveal delay={160}>
          <div className="h-full rounded-2xl border bg-card p-6 shadow-sm">
            <h3 className="font-semibold">The objections it can raise</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Each carries a blocking or advisory severity, and each is traceable to a tool result.
            </p>
            <ul className="mt-4 flex flex-wrap gap-2">
              {OBJECTIONS.map((code) => (
                <li
                  key={code}
                  className="rounded-md border bg-muted/40 px-2 py-1 font-mono text-[11px] text-muted-foreground"
                >
                  {code}
                </li>
              ))}
            </ul>
            <p className="mt-5 rounded-lg border border-primary/25 bg-primary/5 p-3 text-sm leading-relaxed">
              The adversarial phase can only downgrade an approval to{' '}
              <span className="font-medium">needs review</span>. It can never approve, reject or defer. A
              regression test asserts that both modes produce identical decisions for every workload.
            </p>
          </div>
        </Reveal>
      </div>
    </Section>
  )
}
