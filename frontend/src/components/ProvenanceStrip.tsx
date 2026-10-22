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
 * It also discloses how the agent cycle was run. The agent mode is driven by a deterministic
 * stand-in for a language model, not by a real one, and a reviewer who thinks a model was called
 * would read a different kind of trust into the objections than the code actually supports.
 */
export default function ProvenanceStrip({ data }: { data: AnalysisResponse }) {
  const agent = data.mode === 'agent'

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

      {agent && (
        <span
          className={cn(
            'ml-auto rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] text-amber-900',
            'dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200',
          )}
        >
          Agent cycle run by a deterministic stand-in, not a live language model
        </span>
      )}
    </section>
  )
}
