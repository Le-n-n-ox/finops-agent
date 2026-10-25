import {
  Ban,
  CalendarClock,
  CircleCheck,
  Eye,
  FileWarning,
  Gauge,
  History,
  Lock,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react'
import { Reveal } from '../motion'
import { ConfidenceBar } from '../graphics'
import { Section } from './Section'

/* ------------------------------------------------------------------ who decides */

const MODEL_CAN = [
  'Propose a lower request, and argue for or against it',
  'Write the explanation you read on the card',
  'Call read-only tools to gather evidence',
  'Raise red-team objections in the review cycle',
]

const MODEL_CANNOT = [
  'Approve, reject or defer a workload',
  'Override a P99 safety floor',
  'Change a decision the critic has already made',
  'Touch a cluster, a limit, or a deployment',
]

const CHECKS: { icon: LucideIcon; name: string; detail: string }[] = [
  { icon: Gauge, name: 'P99 safety floor', detail: '1.10 × CPU P99, 1.15 × memory P99' },
  { icon: ScrollText, name: 'Data quality', detail: '24 samples over 24 hours' },
  { icon: History, name: 'Freshness', detail: 'latest observation within 72 h' },
  { icon: Ban, name: 'Minimum reduction', detail: 'at least 15% below the current request' },
  { icon: CalendarClock, name: 'Business events', detail: 'campaigns and freezes in the risk window' },
  { icon: FileWarning, name: 'Incident history', detail: 'direct and indirect matches' },
  { icon: CircleCheck, name: 'Minimum saving', detail: 'below it, the change is not worth the risk' },
  { icon: Users, name: 'Protected workloads', detail: 'excluded by name or by criticality headroom' },
]

export function SafetyModel() {
  return (
    <Section
      id="safety"
      eyebrow="The safety model"
      title="The model proposes. The rules decide."
      lede="A language model is good at arguing and bad at being accountable. So it never holds the final status: the deterministic critic re-derives every check from the raw inputs and owns the verdict, and the model can only ever make the answer better explained."
    >
      <div className="grid gap-5 lg:grid-cols-2">
        <Reveal>
          <div className="h-full rounded-2xl border bg-card p-6 shadow-sm">
            <h3 className="flex items-center gap-2 font-semibold">
              <Sparkles className="size-4 text-primary" aria-hidden />
              What the model may do
            </h3>
            <ul className="mt-4 space-y-3">
              {MODEL_CAN.map((item) => (
                <li key={item} className="flex gap-2.5 text-sm leading-relaxed text-muted-foreground">
                  <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </Reveal>

        <Reveal delay={100}>
          <div className="h-full rounded-2xl border bg-card p-6 shadow-sm">
            <h3 className="flex items-center gap-2 font-semibold">
              <Lock className="size-4 text-primary" aria-hidden />
              What only the deterministic critic may do
            </h3>
            <ul className="mt-4 space-y-3">
              {MODEL_CANNOT.map((item) => (
                <li key={item} className="flex gap-2.5 text-sm leading-relaxed text-muted-foreground">
                  <Ban className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </Reveal>
      </div>

      <Reveal delay={60}>
        <div className="mt-6 rounded-2xl border bg-card p-6 shadow-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="flex items-center gap-2 font-semibold">
              <ShieldCheck className="size-4 text-primary" aria-hidden />
              The checks the critic runs on every proposal
            </h3>
            <p className="text-sm text-muted-foreground">Each one is a rule in the policy file, not a line of code.</p>
          </div>
          <ul className="mt-6 grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
            {CHECKS.map(({ icon: Icon, name, detail }) => (
              <li key={name} className="flex gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="size-4" aria-hidden />
                </span>
                <span>
                  <span className="block text-sm font-medium">{name}</span>
                  <span className="block text-sm text-muted-foreground">{detail}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </Reveal>
    </Section>
  )
}

/* ------------------------------------------------------------------ confidence */

const PROPOSAL_FACTORS = [
  { name: 'Sample sufficiency', weight: 25 },
  { name: 'Validation', weight: 20 },
  { name: 'Freshness', weight: 20 },
  { name: 'Usage stability', weight: 20 },
  { name: 'Anomaly evidence', weight: 15 },
]

export function Confidence() {
  return (
    <Section
      id="confidence"
      eyebrow="Confidence"
      title="How much of the report can be traced back to a tool result?"
      lede="A number that nobody can trace is the failure mode that matters most, so traceability carries the largest weight and a fabricated figure costs the most."
      tone="tinted"
    >
      <div className="grid gap-5 lg:grid-cols-5">
        <Reveal className="lp-viz lg:col-span-3">
          <div className="h-full rounded-2xl border bg-card p-6 shadow-sm">
            <h3 className="font-semibold">Verification score</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Scored from 0 to 100, with a one-line derivation shown next to it.
            </p>
            <p className="mt-5 rounded-lg border bg-muted/40 p-3 font-mono text-sm leading-relaxed">
              score = 0.60 × traceability + 0.40 × evidence − overlap − objections
            </p>
            <ConfidenceBar className="mt-6" />
            <p className="mt-6 text-sm leading-relaxed text-muted-foreground">
              Traceability is the share of numbers in the report that appear in a tool result. Evidence
              combines sample sufficiency, metric freshness and freedom from incident or event overlap.
              The objection penalty scales with the number and severity of objections, so risky workloads
              score visibly lower instead of collapsing to a single value.
            </p>
          </div>
        </Reveal>

        <Reveal delay={110} className="lg:col-span-2">
          <div className="h-full rounded-2xl border bg-card p-6 shadow-sm">
            <h3 className="font-semibold">The proposal&rsquo;s own score</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              A separate, deterministic score for the proposal itself, weighted from the policy file.
            </p>
            <ul className="mt-5 space-y-3">
              {PROPOSAL_FACTORS.map((f) => (
                <li key={f.name}>
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="text-muted-foreground">{f.name}</span>
                    <span className="font-medium tabular-nums">{f.weight}%</span>
                  </div>
                  <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${(f.weight / 25) * 100}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
            <p className="mt-5 text-sm text-muted-foreground">
              Invalid or insufficient history caps the score below 40. Priority combines opportunity value
              and confidence, then subtracts anomaly and incident penalties. It is for triage only — it never
              changes a decision.
            </p>
          </div>
        </Reveal>
      </div>
    </Section>
  )
}

/* ------------------------------------------------------------------ human review */

const DIFF = [
  { line: 'resources:', kind: 'plain' },
  { line: '  requests:', kind: 'plain' },
  { line: '    cpu: 800m', kind: 'old' },
  { line: '    cpu: 250m', kind: 'new' },
  { line: '    memory: 3072Mi', kind: 'old' },
  { line: '    memory: 1216Mi', kind: 'new' },
]

export function HumanReview() {
  return (
    <Section
      id="review"
      eyebrow="Human in the loop"
      title="The last word is yours."
      lede="Every recommendation is a proposal for a person. Accepting it for implementation records the decision and produces a review-only patch — it never deploys anything, and a rejection comes back to the agent as a lesson."
    >
      <div className="grid gap-5 lg:grid-cols-5">
        <Reveal className="lg:col-span-3">
          <div className="flex h-full flex-col overflow-hidden rounded-2xl border bg-card shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b px-6 py-4">
              <div>
                <h3 className="text-sm font-semibold">docs-renderer</h3>
                <p className="text-sm text-muted-foreground">platform-tools · risk low · $42.00 / month</p>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
                <CircleCheck className="size-3" aria-hidden />
                Approved
              </span>
            </div>

            <div className="border-b px-6 py-4">
              <p className="text-xs tracking-wide text-muted-foreground uppercase">Proposed patch — review only</p>
              <pre className="mt-3 overflow-x-auto rounded-lg border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
                {DIFF.map((row, i) => (
                  <div
                    key={i}
                    className={
                      row.kind === 'old'
                        ? 'bg-red-500/10 text-red-700 dark:text-red-300'
                        : row.kind === 'new'
                          ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                          : 'text-muted-foreground'
                    }
                  >
                    <span className="mr-3 inline-block w-3 select-none text-muted-foreground/60">
                      {row.kind === 'old' ? '−' : row.kind === 'new' ? '+' : ' '}
                    </span>
                    {row.line}
                  </div>
                ))}
              </pre>
            </div>

            <div className="mt-auto flex flex-wrap items-center gap-2 px-6 py-4">
              <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
                <CircleCheck className="size-4" aria-hidden />
                Accept for implementation
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium text-muted-foreground">
                <X aria-hidden />
                Reject
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium text-muted-foreground">
                <Eye className="size-4" aria-hidden />
                Needs investigation
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t bg-muted/25 px-6 py-3 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">Reviewed by a person</span>
              <span aria-hidden>·</span>
              <span>written to the append-only log</span>
              <span aria-hidden>·</span>
              <span>the agent cannot change it afterwards</span>
            </div>
          </div>
        </Reveal>

        <Reveal delay={110} className="lg:col-span-2">
          <div className="flex h-full flex-col gap-5">
            <div className="rounded-2xl border bg-card p-6 shadow-sm">
              <h3 className="flex items-center gap-2 font-semibold">
                <History className="size-4 text-primary" aria-hidden />
                Rejections come back as lessons
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                A rejection can carry structured reasons, the resource it targets and free-form guidance. The
                next run for that workload replays them to the agent as{' '}
                <span className="font-medium">Historical Lessons</span>, so a reduction a human already
                refused is not re-argued from scratch.
              </p>
              <p className="mt-3 text-sm text-muted-foreground">
                Only rejections become lessons. An acceptance is not a signal to change behaviour.
              </p>
            </div>
            <div className="rounded-2xl border bg-card p-6 shadow-sm">
              <h3 className="flex items-center gap-2 font-semibold">
                <Lock className="size-4 text-primary" aria-hidden />
                The log cannot be rewritten
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                The review log is append-only: database triggers reject updates and deletes on the reviews
                and audit tables. A decision that is later found to be stale is marked stale, and the backend
                refuses to accept it for implementation.
              </p>
            </div>
          </div>
        </Reveal>
      </div>
    </Section>
  )
}
