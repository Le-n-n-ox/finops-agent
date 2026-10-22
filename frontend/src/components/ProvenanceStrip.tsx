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
 * It also discloses how the agent cycle was run. The agent mode is driven by a deterministic
 * stand-in for a language model, not by a real one, and a reviewer who thinks a model was called
 * would read a different kind of trust into the objections than the code actually supports.
 */
export default function ProvenanceStrip({ data }: { data: AnalysisResponse }) {
  const agent = data.mode === 'agent'

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
      {agent && (
        <span
          className={cn(
            'ml-auto rounded border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-900',
            'dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200',
          )}
        >
          Agent cycle run by a deterministic stand-in, not a live language model
        </span>
      )}
    </section>
  )
}
