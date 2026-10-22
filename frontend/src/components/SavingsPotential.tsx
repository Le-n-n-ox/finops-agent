import { ShieldCheck, TrendingUp } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { DECISIONS } from './DecisionBadge'
import type { DecisionStatus, WorkloadResult } from '@/types'

/**
 * Where the money went, including the money we chose not to recommend.
 *
 * A FinOps tool that only reports the savings it is allowed to hand you hides the cost of its own
 * caution. This panel shows the total opportunity the optimizer found, how much of it survived the
 * safety rules, and what held the rest back — so a reviewer can see that a deferral is a
 * deliberate decision with a price, not a gap in the output.
 */

const usd = (n: number) => `$${n.toFixed(2)}`

// Order matters: this is the story of the money, from counted to withheld.
const BREAKDOWN: DecisionStatus[] = ['approved', 'deferred', 'needs_review', 'rejected']

export default function SavingsPotential({ results }: { results: WorkloadResult[] }) {
  const byDecision = new Map<DecisionStatus, number>()
  let potential = 0
  let approved = 0
  for (const r of results) {
    // Potential is what the optimizer found. A workload the critic deferred still has a finding —
    // the saving is in suppressed_saving_usd, not in estimated_monthly_saving_usd.
    const p = (r.proposal.estimated_monthly_saving_usd ?? 0) + (r.proposal.suppressed_saving_usd ?? 0)
    potential += p
    byDecision.set(r.decision, (byDecision.get(r.decision) ?? 0) + p)
    if (r.decision === 'approved') approved += r.monthly_savings_estimate_usd ?? 0
  }
  const heldBack = potential - approved
  const heldPct = potential > 0 ? (heldBack / potential) * 100 : 0

  if (potential <= 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="size-5 text-muted-foreground" aria-hidden />Savings potential
          </CardTitle>
          <CardDescription>Every saving the optimizer found, and what happened to it</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            The optimizer found no reducible request in this analysis, so there is no potential to
            account for.
          </p>
        </CardContent>
      </Card>
    )
  }

  const segments = BREAKDOWN.map((key) => ({
    key,
    amount: byDecision.get(key) ?? 0,
    label: DECISIONS[key].label,
    hex: DECISIONS[key].hex,
  })).filter((s) => s.amount > 0)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TrendingUp className="size-5 text-muted-foreground" aria-hidden />Savings potential
        </CardTitle>
        <CardDescription>
          Everything the optimizer found, and how much of it the safety rules let through
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div
          className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted"
          role="img"
          aria-label={segments.map((s) => `${s.label} ${usd(s.amount)}`).join(', ')}
        >
          {segments.map((s) => (
            <div key={s.key} style={{ width: `${(s.amount / potential) * 100}%`, background: s.hex }} title={`${s.label} ${usd(s.amount)}`} />
          ))}
        </div>

        <dl className="grid gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-xs tracking-wide text-muted-foreground uppercase">Potential</dt>
            <dd className="font-mono text-xl font-semibold tabular-nums">{usd(potential)}</dd>
            <dd className="text-xs text-muted-foreground">per month, if every proposal were applied</dd>
          </div>
          <div>
            <dt className="text-xs tracking-wide text-muted-foreground uppercase">Approved</dt>
            <dd className="font-mono text-xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">{usd(approved)}</dd>
            <dd className="text-xs text-muted-foreground">counted, review-only, per month</dd>
          </div>
          <div>
            <dt className="text-xs tracking-wide text-muted-foreground uppercase">Held back</dt>
            <dd className="font-mono text-xl font-semibold tabular-nums text-amber-600 dark:text-amber-400">{usd(heldBack)}</dd>
            <dd className="text-xs text-muted-foreground">{heldPct.toFixed(0)}% of the potential, deliberately withheld</dd>
          </div>
        </dl>

        <ul className="flex flex-wrap gap-x-4 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
          {segments.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: s.hex }} aria-hidden />
              {s.label}
              <span className="font-mono tabular-nums">{usd(s.amount)}</span>
            </li>
          ))}
        </ul>

        {heldBack > 0 && (
          <p className="flex items-start gap-2 rounded-md border bg-muted/50 p-2.5 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            The held-back amount is not waste. It is the price of not being wrong about an outage, and
            it is listed in full so a reviewer can decide whether to relax a rule.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
