import { Fingerprint, ScrollText, Tag } from 'lucide-react'
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
export default function ProvenanceStrip({ data, source = 'api' }: { data: AnalysisResponse; source?: 'api' | 'mock' }) {
  const live = source === 'api' && data.llm_backend === 'openai-compatible'
  // Three outcomes, not two: a live model, the deterministic stand-in, and a payload that
  // predates the field entirely (older stored reports, bundled mock fixtures). None of the
  // non-live ones may imply a model ran - and the last one may not claim a stand-in ran either,
  // because a fixture is not a stand-in run. Bundled fixtures are not a run at all, and say so.
  const reasoner = source === 'mock'
    ? 'Bundled fixture data, not a backend run'
    : live
      ? `Agent cycle run by ${data.llm_model ?? 'a live language model'}`
      : data.llm_backend === 'simulated'
        ? 'Agent cycle run by a deterministic stand-in, not a live language model'
        : 'No live language model ran this analysis'
  const reasonerTitle = source === 'mock'
    ? 'These numbers come from the bundled mock fixtures. No backend run produced them, and no language model was involved.'
    : live
      ? `Live language model: ${data.llm_model ?? 'unknown model'}${data.llm_base_url ? ` at ${data.llm_base_url}` : ''}.`
      : data.llm_backend === 'simulated'
        ? 'The deterministic stand-in answered the agent turns. No live language model ran.'
        : 'This response does not record which reasoner answered, so no language model is claimed to have run.'

  return (
    <section
      className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border bg-card px-3 py-2 text-xs text-muted-foreground"
      aria-label="Analysis provenance"
    >
      <span className="flex items-center gap-1.5">
        <Tag className="size-3.5 shrink-0" aria-hidden />
        <span>Policy <span className="font-mono text-foreground">{data.policy_version ?? '—'}</span></span>
      </span>
      <span className="flex items-center gap-1.5">
        <ScrollText className="size-3.5 shrink-0" aria-hidden />
        <span>Rules <span className="font-mono text-foreground">{data.rule_version ?? '—'}</span></span>
      </span>
      {data.input_fingerprint && (
        <span className="flex items-center gap-1.5" title="A hash of the input snapshot, so the same inputs give the same analysis.">
          <Fingerprint className="size-3.5 shrink-0" aria-hidden />
          <span>Inputs <span className="font-mono text-foreground">{data.input_fingerprint.slice(0, 12)}</span></span>
        </span>
      )}
      <span className="flex items-center gap-1.5">
        <span>Run <span className="font-mono text-foreground">{data.analysis_id}</span></span>
      </span>
      <span
        className={cn(
          'ml-auto rounded border px-2 py-0.5 text-[11px]',
          live
            ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200'
            : 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200',
        )}
        title={reasonerTitle}
      >
        {reasoner}
      </span>
    </section>
  )
}
