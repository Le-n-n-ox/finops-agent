import { useState } from 'react'
import { AlertTriangle, ChevronRight, Gavel, MessageSquareWarning, Search, ShieldQuestion } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ReviewCycle } from '@/types'

/**
 * The Proposer -> Critic -> Judge review cycle, as it actually ran.
 *
 * Each phase is a real entry from the agent's audit log: the summary it produced, the tools it
 * called, and (for the Judge) the ruling. The phases are collapsible because the summary is the
 * headline and the tool calls are the evidence behind it.
 */

const ROLE_META: Record<string, { label: string; icon: typeof Search; accent: string; blurb: string }> = {
  proposer: {
    label: 'Proposer',
    icon: Search,
    accent: 'text-sky-600 dark:text-sky-400',
    blurb: 'Gathered evidence and argued for or against the change.',
  },
  critic: {
    label: 'Critic',
    icon: ShieldQuestion,
    accent: 'text-amber-600 dark:text-amber-400',
    blurb: 'Red-teamed the proposal and raised grounded objections.',
  },
  judge: {
    label: 'Judge',
    icon: Gavel,
    accent: 'text-violet-600 dark:text-violet-400',
    blurb: 'Weighed the objections against the deterministic verdict.',
  },
}

const VERDICT_STYLE: Record<string, string> = {
  accept: 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300',
  confirm: 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300',
  escalate: 'border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300',
  proceed_with_caveat: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300',
}

function Phase({ cycle, defaultOpen }: { cycle: ReviewCycle; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const meta = ROLE_META[cycle.role] ?? { label: cycle.role, icon: Search, accent: 'text-muted-foreground', blurb: '' }
  const Icon = meta.icon
  const verdictStyle = cycle.verdict ? VERDICT_STYLE[cycle.verdict] : undefined

  return (
    <li className="relative">
      <span
        className={cn('absolute -left-[26px] top-1.5 size-2.5 rounded-full ring-4 ring-card', meta.accent.replace('text-', 'bg-'))}
        aria-hidden
      />
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-start gap-2 rounded-md px-1 py-0.5 text-left outline-none hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        <Icon className={cn('mt-0.5 size-4 shrink-0', meta.accent)} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{meta.label}</span>
            {cycle.verdict && (
              <span className={cn('rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase', verdictStyle)}>
                {cycle.verdict.replaceAll('_', ' ')}
              </span>
            )}
            <span className="text-xs text-muted-foreground">
              {cycle.steps.length} tool call{cycle.steps.length === 1 ? '' : 's'}
              {cycle.objections.length > 0 && ` · ${cycle.objections.length} objection${cycle.objections.length === 1 ? '' : 's'}`}
            </span>
          </span>
          {!open && cycle.summary && (
            <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">{cycle.summary}</span>
          )}
        </span>
        <ChevronRight className={cn('mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')} aria-hidden />
      </button>

      {open && (
        <div className="mt-1.5 space-y-2 pl-6">
          {meta.blurb && <p className="text-xs text-muted-foreground">{meta.blurb}</p>}
          {cycle.summary && <p className="text-sm">{cycle.summary}</p>}

          {cycle.objections.length > 0 && (
            <ul className="space-y-1.5">
              {cycle.objections.map((o) => (
                <li key={o.code} className="flex items-start gap-1.5 text-xs">
                  <AlertTriangle
                    className={cn('mt-0.5 size-3.5 shrink-0', o.severity === 'blocking' ? 'text-red-500' : 'text-amber-500')}
                    aria-hidden
                  />
                  <span>
                    <span className={cn('font-medium', o.severity === 'blocking' ? 'text-red-600 dark:text-red-400' : 'text-amber-700 dark:text-amber-400')}>
                      {o.code}
                    </span>
                    {o.message}
                    {o.source && <span className="text-muted-foreground"> (from {o.source})</span>}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {cycle.steps.length > 0 && (
            <details className="rounded border bg-muted/40 px-2 py-1.5">
              <summary className="cursor-pointer text-xs font-medium">Tool calls ({cycle.steps.length})</summary>
              <ol className="mt-1.5 space-y-1.5">
                {cycle.steps.map((step, i) => (
                  <li key={`${step.tool}-${i}`} className="text-xs">
                    <span className="font-mono font-medium">{step.tool}</span>
                    {step.thought && <span className="text-muted-foreground"> — {step.thought}</span>}
                    {Object.keys(step.params ?? {}).length > 0 && (
                      <span className="ml-1 text-muted-foreground">({Object.entries(step.params).map(([k, v]) => `${k}=${String(v)}`).join(', ')})</span>
                    )}
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
    </li>
  )
}

export default function ReviewCyclePanel({ cycles, lessons }: { cycles?: ReviewCycle[]; lessons?: string[] }) {
  if (!cycles?.length) {
    return (
      <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
        No review cycle recorded. Run the analysis in <span className="font-medium">Agent cycle</span> mode to see the
        Proposer, Critic and Judge reasoning.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {!!lessons?.length && (
        <section className="rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950/40">
          <h4 className="flex items-center gap-1.5 text-sm font-medium">
            <MessageSquareWarning className="size-4 text-amber-600 dark:text-amber-400" aria-hidden />
            Historical lessons
          </h4>
          <ul className="mt-1.5 space-y-1">
            {lessons.map((lesson) => (
              <li key={lesson} className="text-xs text-muted-foreground">• {lesson}</li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-muted-foreground">A human rejected these before. The proposer was told about them.</p>
        </section>
      )}

      <ol className="relative space-y-3 border-l pl-5">
        {cycles.map((cycle, i) => (
          <Phase key={`${cycle.role}-${i}`} cycle={cycle} defaultOpen={i === 0} />
        ))}
      </ol>
    </div>
  )
}
