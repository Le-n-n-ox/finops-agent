import { useEffect, useState } from 'react'
import {
  ArrowRight,
  CircleCheck,
  Cpu,
  Gauge,
  Lock,
  MemoryStick,
  ServerCog,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react'
import { fetchDashboard } from '@/api'
import type { DashboardSummary } from '@/types'
import { Button } from '@/components/ui/button'
import ThemeToggle from '@/components/ThemeToggle'
import { goHome } from '@/hooks/useHashRoute'
import { AnimatedNumber, Reveal } from './motion'
import { DECISION_COLOR, DECISION_LABEL, DECISION_ORDER } from './decisions'
import { DecisionRing, UsageSparkline } from './graphics'
import { AgentCycle, Pipeline, Problem } from './sections/HowItWorks'
import { Confidence, HumanReview, SafetyModel } from './sections/Safety'
import { Limits, Panels, Stack } from './sections/Surfaces'
import './landing.css'

/**
 * The landing page.
 *
 * It is the front door: the workspace is one click away, and the page explains what the
 * system is before asking anyone to trust it with a cluster.
 */

/** The demo figures, used when no backend is reachable. */
const DEMO = {
  workloads_analyzed: 12,
  estimated_monthly_savings_usd: 92.75,
  potential_savings_usd: 149.25,
  held_back_usd: 56.5,
  approved: 4,
  deferred: 4,
  needs_review: 0,
  rejected: 0,
  no_change: 4,
}

/** Scrolls to a section without touching the hash: the hash is the app's router. */
function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function AnchorLink({ id, children }: { id: string; children: string }) {
  return (
    <a
      href={`#${id}`}
      onClick={(e) => {
        e.preventDefault()
        scrollTo(id)
      }}
      className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      {children}
    </a>
  )
}

/* ------------------------------------------------------------------ header */

function LandingHeader() {
  return (
    <header className="app-nav sticky top-0 z-40 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex max-w-[1200px] items-center gap-3 px-4 py-3 lg:px-6">
        <a href="#top" className="flex items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <ServerCog className="size-5" aria-hidden />
          </span>
          <span className="hidden sm:block">
            <span className="block text-sm leading-tight font-semibold">Kubernetes FinOps Agent</span>
            <span className="block text-xs text-muted-foreground">Evidence-based resource recommendations</span>
          </span>
        </a>

        <nav className="ml-auto hidden items-center gap-1 md:flex" aria-label="Sections">
          <AnchorLink id="pipeline">Pipeline</AnchorLink>
          <AnchorLink id="cycle">Review cycle</AnchorLink>
          <AnchorLink id="safety">Safety</AnchorLink>
          <AnchorLink id="review">Review</AnchorLink>
          <AnchorLink id="panels">Panels</AnchorLink>
        </nav>

        <div className="ml-auto flex items-center gap-2 md:ml-0">
          <ThemeToggle />
          <Button size="sm" onClick={goHome}>
            Open workspace
            <ArrowRight aria-hidden />
          </Button>
        </div>
      </div>
    </header>
  )
}

/* ------------------------------------------------------------------ hero */

function Hero({ stats, live }: { stats: typeof DEMO; live: boolean }) {
  return (
    <section id="top" className="relative overflow-hidden">
      <div aria-hidden className="lp-grid absolute inset-0 -z-10" />
      <div
        aria-hidden
        className="absolute -top-40 left-1/2 -z-10 h-[36rem] w-[64rem] -translate-x-1/2 rounded-full bg-primary/12 blur-3xl"
      />

      <div className="mx-auto grid w-full max-w-[1200px] items-center gap-14 px-4 py-16 lg:grid-cols-[1.05fr_0.95fr] lg:px-6 lg:py-24">
        <div>
          <Reveal>
            <span className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/5 px-3 py-1 text-xs font-medium text-primary">
              <Lock className="size-3.5" aria-hidden />
              Recommendation-only · it never changes a cluster
            </span>
          </Reveal>

          <Reveal delay={80}>
            <h1 className="mt-6 text-balance text-4xl font-semibold tracking-tight text-balance sm:text-5xl lg:text-6xl">
              Kubernetes requests, sized by evidence instead of hope.
            </h1>
          </Reveal>

          <Reveal delay={160}>
            <p className="mt-6 max-w-xl text-pretty text-lg leading-relaxed text-muted-foreground">
              The agent reads historical CPU and memory usage, proposes smaller requests, and has a
              deterministic critic rule on them against P99 safety floors, business events and incident
              history. A human makes the final call — and every recommendation carries the trail that
              produced it.
            </p>
          </Reveal>

          <Reveal delay={240}>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Button size="lg" onClick={goHome}>
                Open the workspace
                <ArrowRight aria-hidden />
              </Button>
              <Button
                size="lg"
                variant="outline"
                onClick={() => scrollTo('pipeline')}
              >
                See the pipeline
              </Button>
            </div>
          </Reveal>

          <Reveal delay={320}>
            <p className="mt-6 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <ShieldCheck className="size-3.5" aria-hidden />
              Requests are only ever recommended downward · limits are never touched · nothing is applied
            </p>
          </Reveal>
        </div>

        <Reveal delay={200}>
          <div className="relative">
            <div aria-hidden className="absolute -inset-10 -z-10">
              <div className="lp-drift absolute -top-6 left-2 size-64 rounded-full bg-primary/20 blur-3xl" />
              <div
                className="lp-drift absolute right-0 bottom-4 size-72 rounded-full bg-indigo-500/15 blur-3xl"
                style={{ animationDelay: '-8s' }}
              />
            </div>

            <div className="lp-sheen lp-viz relative overflow-hidden rounded-2xl border bg-card shadow-2xl">
              <div className="flex items-start justify-between gap-4 border-b px-6 py-4">
                <div>
                  <p className="font-semibold">docs-renderer</p>
                  <p className="text-sm text-muted-foreground">platform-tools · risk low</p>
                </div>
                <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
                  <CircleCheck className="size-3" aria-hidden />
                  Approved
                </span>
              </div>

              <div className="space-y-4 px-6 py-5">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <Cpu className="size-3.5" aria-hidden />
                      CPU request
                    </p>
                    <p className="mt-1 text-xl font-semibold tabular-nums">
                      250 m <span className="text-sm font-normal text-muted-foreground line-through">800 m</span>
                    </p>
                  </div>
                  <div>
                    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <MemoryStick className="size-3.5" aria-hidden />
                      Memory request
                    </p>
                    <p className="mt-1 text-xl font-semibold tabular-nums">
                      1216 Mi <span className="text-sm font-normal text-muted-foreground line-through">3072</span>
                    </p>
                  </div>
                </div>

                <div>
                  <p className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>Usage against the request</span>
                    <span className="tabular-nums">p99 210 m</span>
                  </p>
                  <UsageSparkline className="mt-2" />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-px border-t bg-border">
                <div className="bg-card px-6 py-4">
                  <p className="text-xs text-muted-foreground">Saving / month</p>
                  <p className="mt-1 text-lg font-semibold tabular-nums">$42.00</p>
                </div>
                <div className="bg-card px-6 py-4">
                  <p className="text-xs text-muted-foreground">Confidence</p>
                  <p className="mt-1 text-lg font-semibold tabular-nums">78 / 100</p>
                </div>
              </div>
            </div>

            <span className="lp-float absolute -top-7 -right-4 hidden items-center gap-2 rounded-xl border bg-card px-3 py-2 text-xs font-medium shadow-lg lg:flex">
              <Gauge className="size-3.5 text-primary" aria-hidden />
              8,640 samples
            </span>
            <span className="lp-bob absolute -bottom-7 -left-5 hidden items-center gap-2 rounded-xl border bg-card px-3 py-2 text-xs font-medium shadow-lg lg:flex">
              <TrendingUp className="size-3.5 text-primary" aria-hidden />
              −69% CPU request
            </span>
          </div>
        </Reveal>
      </div>

      <Stats stats={stats} live={live} />
    </section>
  )
}

/* ------------------------------------------------------------------ stats */

function Stats({ stats, live }: { stats: typeof DEMO; live: boolean }) {
  const items = [
    {
      value: stats.workloads_analyzed,
      label: 'workloads evaluated',
      note: 'deployments and stateful sets',
      format: (n: number) => Math.round(n).toString(),
    },
    {
      value: stats.estimated_monthly_savings_usd,
      label: 'estimated monthly savings',
      note: 'counted for approved decisions only',
      format: (n: number) => `$${n.toFixed(2)}`,
    },
    {
      value: stats.potential_savings_usd,
      label: 'total potential',
      note: 'everything the optimizer found',
      format: (n: number) => `$${n.toFixed(2)}`,
    },
    {
      value: stats.held_back_usd,
      label: 'held back by the rules',
      note: 'shown with its price, not as a gap',
      format: (n: number) => `$${n.toFixed(2)}`,
    },
  ]

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 lg:px-6">
      <Reveal>
        <div className="overflow-hidden rounded-2xl border bg-card shadow-sm">
          <div className="flex items-center justify-between gap-3 border-b px-6 py-3">
            <p className="text-sm font-medium">From the last analysis on this instance</p>
            <span
              className={
                live
                  ? 'inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300'
                  : 'inline-flex items-center gap-2 rounded-full border px-2.5 py-0.5 text-xs font-medium text-muted-foreground'
              }
            >
              <span
                aria-hidden
                className={
                  live
                    ? 'lp-blink size-1.5 rounded-full bg-emerald-500'
                    : 'size-1.5 rounded-full bg-muted-foreground/50'
                }
              />
              {live ? 'Live backend' : 'Demo data · API offline'}
            </span>
          </div>
          <dl className="grid gap-px bg-border sm:grid-cols-2 lg:grid-cols-4">
            {items.map((item) => (
              <div key={item.label} className="bg-card px-6 py-6">
                <dd className="text-3xl font-semibold tracking-tight tabular-nums">
                  <AnimatedNumber value={item.value} format={item.format} />
                </dd>
                <dt className="mt-2 text-sm font-medium">{item.label}</dt>
                <p className="mt-0.5 text-sm text-muted-foreground">{item.note}</p>
              </div>
            ))}
          </dl>
        </div>
      </Reveal>
    </div>
  )
}

/* ------------------------------------------------------------------ decisions strip */

/**
 * A small, honest look at how the last run was ruled on. It reads the dashboard summary, so
 * on a live backend it is the real split; offline it falls back to the demo figures.
 */
function DecisionStrip({ stats }: { stats: typeof DEMO }) {
  const counts = {
    approved: stats.approved,
    deferred: stats.deferred,
    needs_review: stats.needs_review,
    rejected: stats.rejected,
    no_change: stats.no_change,
  }
  const total = Object.values(counts).reduce((n, v) => n + v, 0)

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-4 lg:px-6">
      <Reveal>
        <div className="grid items-center gap-8 rounded-2xl border bg-card p-6 shadow-sm lg:grid-cols-[auto_1fr]">
          <div className="relative mx-auto size-[190px] shrink-0">
            <DecisionRing counts={counts} />
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-3xl font-semibold tabular-nums">{total}</span>
              <span className="text-xs text-muted-foreground">workloads</span>
            </div>
          </div>
          <div>
            <h3 className="text-lg font-semibold">How the critic ruled on the last run</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Every proposal ends in one of five states, and the reasons for each are on the card.
            </p>
            <ul className="mt-5 grid gap-x-8 gap-y-2.5 sm:grid-cols-2">
              {DECISION_ORDER.map((key) => (
                <li key={key} className="flex items-center gap-2.5 text-sm">
                  <span
                    className="size-2.5 shrink-0 rounded-full"
                    style={{ background: DECISION_COLOR[key] }}
                    aria-hidden
                  />
                  <span className="flex-1 text-muted-foreground">{DECISION_LABEL[key]}</span>
                  <span className="font-medium tabular-nums">{counts[key]}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Reveal>
    </div>
  )
}

/* ------------------------------------------------------------------ footer */

function LandingFooter() {
  return (
    <footer className="border-t bg-muted/25">
      <div className="mx-auto flex w-full max-w-[1200px] flex-col items-center gap-6 px-4 py-16 text-center lg:px-6">
        <Reveal>
          <h2 className="text-balance text-3xl font-semibold tracking-tight sm:text-4xl">
            Run it against your own cluster.
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-pretty text-muted-foreground">
            The workspace runs the whole path: the analysis, the evidence, the what-if, the review form and
            the audit export. Nothing it produces reaches a cluster on its own.
          </p>
          <Button size="lg" className="mt-8" onClick={goHome}>
            Open the workspace
            <ArrowRight aria-hidden />
          </Button>
        </Reveal>
        <p className="text-xs text-muted-foreground">
          Prototype · recommendation-only · savings are illustrative estimates, not guaranteed bill reductions.
        </p>
      </div>
    </footer>
  )
}

/* ------------------------------------------------------------------ page */

export default function LandingPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)

  useEffect(() => {
    let alive = true
    void fetchDashboard().then((res) => {
      if (alive && res.data) setSummary(res.data)
    })
    return () => {
      alive = false
    }
  }, [])

  const stats = summary
    ? {
        workloads_analyzed: summary.workloads_analyzed,
        estimated_monthly_savings_usd: summary.estimated_monthly_savings_usd,
        potential_savings_usd: summary.potential_savings_usd,
        held_back_usd: summary.held_back_usd,
        approved: summary.approved,
        deferred: summary.deferred,
        needs_review: summary.needs_review,
        rejected: summary.rejected,
        no_change: summary.no_change,
      }
    : DEMO

  return (
    <div className="min-h-screen bg-background">
      <LandingHeader />
      <main>
        <Hero stats={stats} live={!!summary} />
        <DecisionStrip stats={stats} />
        <Problem />
        <Pipeline />
        <AgentCycle />
        <SafetyModel />
        <Confidence />
        <HumanReview />
        <Panels />
        <Limits />
        <Stack />
      </main>
      <LandingFooter />
    </div>
  )
}
