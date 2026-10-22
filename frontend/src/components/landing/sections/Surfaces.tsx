import {
  Activity,
  CalendarClock,
  FileText,
  FlaskConical,
  GitBranch,
  History,
  LayoutDashboard,
  Scale,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Target,
  type LucideIcon,
} from 'lucide-react'
import { Reveal } from '../motion'
import { Section } from './Section'

/* ------------------------------------------------------------------ the panels */

const PANELS: { icon: LucideIcon; name: string; body: string }[] = [
  {
    icon: GitBranch,
    name: 'Cycle',
    body: 'The Proposer → Critic → Judge phases as they ran: each summary, each tool call, each objection, the ruling.',
  },
  {
    icon: FlaskConical,
    name: 'What-if',
    body: 'Move the CPU and memory requests and the deterministic critic re-decides against your numbers. Nothing is saved, no patch is produced.',
  },
  {
    icon: History,
    name: 'Review history',
    body: 'What a human already decided about this workload, with the structured rejection reasons the agent replays.',
  },
  {
    icon: ScrollText,
    name: 'Decision history',
    body: 'Every decision the critic has made, searchable across reports. A decision whose metrics have moved is marked stale.',
  },
  {
    icon: Activity,
    name: 'Trend',
    body: 'Approved savings over successive runs, with deferred and needs-review counts alongside.',
  },
  {
    icon: CalendarClock,
    name: 'Business events',
    body: 'Campaigns and freezes split into live, upcoming and past, with the services each one puts at risk.',
  },
  {
    icon: ShieldCheck,
    name: 'Safety policy',
    body: 'Every field the critic reads, editable. Saving appends a version and flags earlier reports as expired.',
  },
  {
    icon: Target,
    name: 'Savings potential',
    body: 'Everything the optimizer found, how much survived the safety rules, and what was held back — with its price.',
  },
  {
    icon: LayoutDashboard,
    name: 'Top opportunities',
    body: 'Findings ranked by savings × confidence ÷ risk, so the short list is at the top rather than buried.',
  },
]

export function Panels() {
  return (
    <Section
      id="panels"
      eyebrow="The surfaces"
      title="What you get once you are inside."
      lede="The backend exposes the analysis; the frontend makes it reviewable. Each of these is a panel a reviewer can open, read and argue with."
    >
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {PANELS.map(({ icon: Icon, name, body }, i) => (
          <Reveal key={name} delay={(i % 3) * 80}>
            <li className="group h-full rounded-xl border bg-card p-5 shadow-sm transition-colors hover:border-primary/40">
              <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Icon className="size-4" aria-hidden />
              </span>
              <h3 className="mt-4 font-semibold">{name}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
            </li>
          </Reveal>
        ))}
      </ul>

      <Reveal delay={80}>
        <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border bg-card px-6 py-5 shadow-sm">
          <span className="flex items-center gap-2 text-sm font-semibold">
            <FileText className="size-4 text-primary" aria-hidden />
            Provenance strip
          </span>
          <span className="text-sm text-muted-foreground">
            The policy version, the rule version, the input fingerprint and the run id sit above every analysis,
            so a recommendation can be traced back to the rules and the data that produced it.
          </span>
          <code className="rounded-md border bg-muted/40 px-2 py-1 font-mono text-xs">sha256:cd92d0ea…</code>
        </div>
      </Reveal>
    </Section>
  )
}

/* ------------------------------------------------------------------ the limits */

const LIMITS: { title: string; body: string }[] = [
  {
    title: 'The savings are illustrative',
    body: 'The demo uses $25 per CPU core-month and $4 per GiB-month. Those are demo rates, not a cloud-provider quote and not a forecast of a real bill. Validate against your own pricing before you make a business decision.',
  },
  {
    title: 'The model is simple on purpose',
    body: 'It does not account for provider, region, commitment or discount terms, node packing, autoscaling, shared overhead, workload changes, or billing granularity. Treat the number as directional.',
  },
  {
    title: 'The data is a fixture',
    body: 'The bundled datasets are synthetic. They demonstrate outcomes; they are not live production telemetry. A Zetaris connection replaces them with real tables when it is configured.',
  },
  {
    title: 'The runtime seam is a seam',
    body: 'The Meterless / Nightshift runner routes the collector, optimizer and critic steps through a single interface, but the runner still executes each function locally. It is an integration point, not a claim of remote execution.',
  },
  {
    title: 'The model may be a stand-in',
    body: 'Unless a language model is configured, the agent cycle runs on a deterministic stand-in. The decisions are identical either way — only the reasoning and the wording differ.',
  },
  {
    title: 'Nothing is ever applied',
    body: 'No deployment is patched, no limit is changed, and no request is raised. A workload is only ever recommended downward, and only after a person agrees.',
  },
]

export function Limits() {
  return (
    <Section
      id="limits"
      eyebrow="The limits"
      title="What this does not do."
      lede="A recommendation tool that hides its edges is worse than no tool. These are the boundaries of the prototype, stated plainly."
      tone="tinted"
    >
      <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {LIMITS.map((limit, i) => (
          <Reveal key={limit.title} delay={(i % 3) * 80}>
            <li className="h-full rounded-xl border bg-card p-5 shadow-sm">
              <h3 className="font-semibold">{limit.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{limit.body}</p>
            </li>
          </Reveal>
        ))}
      </ul>
    </Section>
  )
}

/* ------------------------------------------------------------------ the stack */

export function Stack() {
  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 lg:px-6">
      <Reveal>
        <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-center text-sm text-muted-foreground">
          <span className="flex items-center gap-2">
            <Scale className="size-4 text-primary" aria-hidden />
            FastAPI · deterministic critic
          </span>
          <span className="flex items-center gap-2">
            <Activity className="size-4 text-primary" aria-hidden />
            React · Vite · TypeScript
          </span>
          <span className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-primary" aria-hidden />
            SQLite · append-only audit log
          </span>
          <span className="flex items-center gap-2">
            <Sparkles className="size-4 text-primary" aria-hidden />
            NVIDIA NIM · optional
          </span>
        </div>
      </Reveal>
    </div>
  )
}
