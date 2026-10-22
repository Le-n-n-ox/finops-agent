import { useState } from 'react'
import { toast } from 'sonner'
import { Calculator, Loader2, RotateCcw, TrendingDown } from 'lucide-react'
import { simulate } from '@/api'
import { Button } from '@/components/ui/button'
import { DecisionBadge } from './DecisionBadge'
import { cn } from '@/lib/utils'
import type { SimulationResult, WorkloadResult } from '@/types'

/**
 * What-if: propose your own request values and see what the critic would decide.
 *
 * The backend re-runs the deterministic critic against the hypothetical numbers and returns the
 * verdict it would reach. Nothing is saved and no patch is produced - this is a negotiation, not a
 * recommendation. The deterministic critic still owns the answer; the agent has no say here.
 *
 * The sliders start from the optimizer's candidate where one exists, including a candidate the
 * critic refused. Seeding them from the *current* request instead would put every reduction below
 * the P99 floor, and the simulator would only ever be able to answer "rejected" - useless for the
 * workloads a reviewer most wants to challenge.
 */

export default function Simulator({ result, disabledReason }: { result: WorkloadResult; disabledReason?: string }) {
  const { current, proposed, metrics, suppressed_proposal: suppressed } = result.proposal
  // The optimizer's candidate: the live proposal, or the one a safety rule refused.
  const candidate = proposed ?? suppressed ?? null
  const [cpu, setCpu] = useState<number>(candidate?.cpu_request_millicores ?? current.cpu_request_millicores ?? 0)
  const [mem, setMem] = useState<number>(candidate?.memory_request_mib ?? current.memory_request_mib ?? 0)
  const [simulation, setSimulation] = useState<SimulationResult | null>(null)
  const [busy, setBusy] = useState(false)

  const cpuMin = 10
  const cpuMax = Math.max(current.cpu_request_millicores ?? 1000, 100)
  const memMin = 16
  const memMax = Math.max(current.memory_request_mib ?? 1024, 128)

  const run = async () => {
    setBusy(true)
    try {
      setSimulation(await simulate(result.workload_id, {
        cpu_request_millicores: cpu || null,
        memory_request_mib: mem || null,
      }))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not run the simulation')
    } finally {
      setBusy(false)
    }
  }

  const reset = () => {
    setCpu(candidate?.cpu_request_millicores ?? current.cpu_request_millicores ?? 0)
    setMem(candidate?.memory_request_mib ?? current.memory_request_mib ?? 0)
    setSimulation(null)
  }

  const headroom = (request: number, p99: number | null | undefined) =>
    p99 ? Math.round((request / p99 - 1) * 100) : null

  return (
    <section className="space-y-3" aria-label="What-if simulator">
      <p className="flex items-start gap-2 rounded-md border bg-muted/50 p-2.5 text-xs text-muted-foreground">
        <Calculator className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Change the request values and the critic re-decides. Nothing is saved, no patch is produced, and nothing is
        applied to a cluster.
      </p>

      {disabledReason && (
        <p className="rounded-md border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          {disabledReason}
        </p>
      )}

      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="flex items-baseline justify-between text-xs">
            <span className="font-medium">CPU request</span>
            <span className="text-muted-foreground tabular-nums">
              {cpu} m
              {metrics.cpu_p99 ? <span className="ml-1">· p99 {metrics.cpu_p99} m</span> : null}
              {headroom(cpu, metrics.cpu_p99) !== null && (
                <span className={cn('ml-1 font-medium', headroom(cpu, metrics.cpu_p99)! < 0 ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400')}>
                  {headroom(cpu, metrics.cpu_p99)}% headroom
                </span>
              )}
            </span>
          </span>
          <input
            type="range"
            min={cpuMin}
            max={cpuMax}
            step={10}
            value={cpu}
            onChange={(e) => { setCpu(Number(e.target.value)); setSimulation(null) }}
            aria-label="Simulated CPU request in millicores"
            className="w-full accent-primary"
          />
        </label>

        <label className="block space-y-1">
          <span className="flex items-baseline justify-between text-xs">
            <span className="font-medium">Memory request</span>
            <span className="text-muted-foreground tabular-nums">
              {mem} MiB
              {metrics.memory_p99 ? <span className="ml-1">· p99 {metrics.memory_p99} MiB</span> : null}
              {headroom(mem, metrics.memory_p99) !== null && (
                <span className={cn('ml-1 font-medium', headroom(mem, metrics.memory_p99)! < 0 ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400')}>
                  {headroom(mem, metrics.memory_p99)}% headroom
                </span>
              )}
            </span>
          </span>
          <input
            type="range"
            min={memMin}
            max={memMax}
            step={64}
            value={mem}
            onChange={(e) => { setMem(Number(e.target.value)); setSimulation(null) }}
            aria-label="Simulated memory request in MiB"
            className="w-full accent-primary"
          />
        </label>
      </div>

      <p className="text-xs text-muted-foreground">
        {candidate
          ? `Starting from the optimizer's candidate: ${candidate.cpu_request_millicores} m CPU, ${candidate.memory_request_mib} MiB memory.`
          : `Starting from the current request: ${current.cpu_request_millicores} m CPU, ${current.memory_request_mib} MiB memory.`}
      </p>

      <div className="flex gap-2">
        <Button size="sm" onClick={() => void run()} disabled={busy || !!disabledReason}>
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : <TrendingDown aria-hidden />}
          {busy ? 'Asking the critic…' : 'What would the critic decide?'}
        </Button>
        <Button size="sm" variant="ghost" onClick={reset} disabled={busy}>
          <RotateCcw aria-hidden />Reset
        </Button>
      </div>

      {simulation && (
        <div className="space-y-2 rounded-md border p-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">The critic would say:</span>
            <DecisionBadge decision={simulation.simulated.decision} />
            <span className="text-muted-foreground">instead of</span>
            <DecisionBadge decision={simulation.original_decision} />
          </div>
          <p className="text-xs text-muted-foreground">{simulation.simulated.reason}</p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
            <dt className="text-muted-foreground">CPU change</dt>
            <dd className="tabular-nums">{simulation.cpu_change_pct === null ? '—' : `${simulation.cpu_change_pct > 0 ? '+' : ''}${simulation.cpu_change_pct}%`}</dd>
            <dt className="text-muted-foreground">Memory change</dt>
            <dd className="tabular-nums">{simulation.memory_change_pct === null ? '—' : `${simulation.memory_change_pct > 0 ? '+' : ''}${simulation.memory_change_pct}%`}</dd>
            <dt className="text-muted-foreground">Monthly estimate</dt>
            <dd className="tabular-nums">${simulation.estimated_monthly_saving_usd.toFixed(2)}</dd>
            <dt className="text-muted-foreground">Risk</dt>
            <dd>{simulation.simulated.risk_level}</dd>
          </dl>
          <p className="text-xs text-muted-foreground">{simulation.label}</p>
        </div>
      )}
    </section>
  )
}
