import { Fingerprint, ScrollText, Tag, type LucideIcon } from 'lucide-react'
import type { AnalysisResponse } from '@/types'
import { cn } from '@/lib/utils'

/**
 * What produced this analysis, and under which rules.
 *
 * A recommendation is only auditable if you can say which policy version, which rule version and
 * which input snapshot it came from. Those three are on the response; this strip puts them on
 * screen next to the numbers they produced.
 *
 * It also discloses which reasoner ran. When a live language model answered the agent turns the
 * badge names it. When the deterministic stand-in did, the badge says so in amber: a reviewer who
 * thinks a model was called would read a different kind of trust into the objections than the code
 * actually supports.
 */
export default function ProvenanceStrip({ data }: { data: AnalysisResponse }) {
  const live = data.llm_backend === 'openai-compatible'
  // Three outcomes, not two: a live model, the deterministic stand-in, and a payload that
  // predates the field entirely (older stored reports, bundled mock fixtures). None of the
  // non-live ones may imply a model ran - and the last one may not claim a stand-in ran either,
  // because a fixture is not a stand-in run.
  const reasoner = live
    ? `Agent cycle run by ${data.llm_model ?? 'a live language model'}`
    : data.llm_backend === 'simulated'
      ? 'Agent cycle run by a deterministic stand-in, not a live language model'
      : 'No live language model ran this analysis'
  const reasonerTitle = live
    ? `Live language model: ${data.llm_model ?? 'unknown model'}${data.llm_base_url ? ` at ${data.llm_base_url}` : ''}.`
    : data.llm_backend === 'simulated'
      ? 'The deterministic stand-in answered the agent turns. No live language model ran.'
      : 'This response does not record which reasoner answered, so no language model is claimed to have run.'

  const items: { icon: LucideIcon; label: string; value: string; title?: string }[] = [
    { icon: Tag, label: 'Policy', value: data.policy_version ?? '—' },
    { icon: ScrollText, label: 'Rules', value: data.rule_version ?? '—' },
    ...(data.input_fingerprint
      ? [
          {
            icon: Fingerprint,
            label: 'Inputs',
            value: data.input_fingerprint.slice(0, 12),
            title: 'A hash of the input snapshot, so the same inputs give the same analysis.',
          },
        ]
      : []),
    { icon: Tag, label: 'Run', value: data.analysis_id },
  ]

  return (
    <section
      className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border bg-card px-5 py-3.5"
      aria-label="Analysis provenance"
    >
      {items.map(({ icon: Icon, label, value, title }) => (
        <span key={label} className="flex items-center gap-2" title={title}>
          <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <span className="text-xs tracking-wide text-muted-foreground uppercase">{label}</span>
          <span className="font-mono text-xs font-medium text-foreground">{value}</span>
        </span>
      ))}

      <span
        className={cn(
          'ml-auto rounded-md border px-2.5 py-1 text-[11px]',
          live
            ? 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200'
            : 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200',
        )}
        title={reasonerTitle}
      >
        {reasoner}
      </span>
    </section>
  )
}
