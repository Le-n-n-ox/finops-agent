import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Loader2, Lock, RotateCcw, Save, ShieldCheck } from 'lucide-react'
import { fetchDefaultPolicy, fetchPolicy, savePolicy } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { CriticPolicy } from '@/types'

/**
 * The safety policy, editable.
 *
 * These are the guardrails the critic enforces: how much a request may be cut, which workloads are
 * protected, how long an event freezes a change, and the headroom applied per criticality. Saving
 * appends a new policy version; reports analysed under the old one are flagged as expired.
 *
 * Every field the critic reads is editable here. A policy editor that only shows half the rules
 * is worse than none, because the reviewer believes they are looking at the whole policy.
 */

interface FieldProps {
  label: string
  hint: string
  children: React.ReactNode
}

function Field({ label, hint, children }: FieldProps) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium">{label}</span>
      {children}
      <span className="block text-xs text-muted-foreground">{hint}</span>
    </label>
  )
}

const inputClass =
  'h-8 w-full rounded-md border bg-background px-2 text-sm tabular-nums outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/**
 * Whether a payload is a policy this editor can render completely.
 *
 * The editor reads every field the critic enforces, and there is no error boundary above it:
 * a payload missing one of them - a partial response, or a policy written by an older
 * version - would throw during render and take the whole app down with it, including the
 * navigation. A policy the editor cannot show in full is not worth showing half of, so an
 * incomplete one is treated as unavailable.
 */
function isRenderablePolicy(value: unknown): value is CriticPolicy {
  if (!value || typeof value !== 'object') return false
  const p = value as Record<string, unknown>
  const numeric = [
    'max_reduction_pct', 'min_monthly_saving_usd', 'min_samples', 'stale_after_hours',
    'top_n_findings', 'cpu_floor_p99_multiplier', 'memory_floor_p99_multiplier',
    'min_cpu_request_millicores', 'min_memory_request_mib', 'risk_window_hours',
    'event_freeze_hours_after', 'change_window_start_hour', 'change_window_end_hour',
  ]
  if (!numeric.every((key) => typeof p[key] === 'number')) return false
  if (typeof p.version !== 'string' || typeof p.rule_version !== 'string') return false
  if (!Array.isArray(p.change_window_days)) return false
  if (!Array.isArray(p.protected_workloads) || !Array.isArray(p.excluded_workloads)) return false
  if (!Array.isArray(p.policy_exceptions)) return false
  if (!p.criticality_headroom || typeof p.criticality_headroom !== 'object') return false
  return true
}

export default function PolicyPanel({ onSaved }: { onSaved?: () => void }) {
  const [policy, setPolicy] = useState<CriticPolicy | null>(null)
  const [original, setOriginal] = useState<CriticPolicy | null>(null)
  const [defaults, setDefaults] = useState<CriticPolicy | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    fetchPolicy().then((r) => {
      if (!alive) return
      const loaded = r.data && isRenderablePolicy(r.data) ? r.data : null
      setPolicy(loaded)
      setOriginal(loaded)
      setLoading(false)
    })
    // The defaults are a convenience, not a requirement: if the endpoint is missing, the editor
    // still works, it just cannot offer a reset. A malformed one is treated as missing, for
    // the same reason the policy itself is.
    void fetchDefaultPolicy().then((r) => {
      if (alive && r.data && isRenderablePolicy(r.data)) setDefaults(r.data)
    })
    return () => { alive = false }
  }, [])

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />Loading the safety policy…
        </CardContent>
      </Card>
    )
  }

  if (!policy) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          The policy could not be read from the API. The critic is running on the policy in <code>data/policy.yaml</code>.
        </CardContent>
      </Card>
    )
  }

  const set = <K extends keyof CriticPolicy>(key: K, value: CriticPolicy[K]) => setPolicy({ ...policy, [key]: value })
  const dirty = JSON.stringify(policy) !== JSON.stringify(original)

  const resetToDefaults = () => {
    if (!defaults) return
    // The version fields are audit labels, not thresholds: resetting them would misreport which
    // policy version produced a decision. Everything else goes back to the shipped default.
    setPolicy({ ...defaults, version: policy.version, rule_version: policy.rule_version })
    toast.info('Fields reset to the built-in defaults. Nothing is saved until you save.')
  }

  const save = async () => {
    setBusy(true)
    try {
      const saved = await savePolicy(policy)
      if (!isRenderablePolicy(saved)) {
        // The save may well have succeeded; the response just cannot be rendered. Say so
        // rather than putting a half-policy on screen.
        toast.error('The policy was saved, but the response could not be read back.')
        onSaved?.()
        return
      }
      setPolicy(saved)
      setOriginal(saved)
      toast.success(`Policy saved as version ${saved.version}. Earlier reports are now flagged as expired.`)
      onSaved?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save the policy')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-5 text-muted-foreground" aria-hidden />Safety policy
        </CardTitle>
        <CardDescription>
          The rules the critic enforces. Version <span className="font-mono">{policy.version}</span> · rules{' '}
          <span className="font-mono">{policy.rule_version}</span> — saving appends a new version and expires
          earlier reports.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="space-y-3" aria-label="Thresholds">
          <h3 className="text-sm font-semibold">Thresholds</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Max reduction %" hint="Largest allowed cut per resource.">
              <input type="number" min={1} max={100} step={1} value={policy.max_reduction_pct}
                     onChange={(e) => set('max_reduction_pct', Number(e.target.value))} className={inputClass} />
            </Field>
            <Field label="Min monthly saving $" hint="Below this, a cut is not worth the risk.">
              <input type="number" min={0} step={0.5} value={policy.min_monthly_saving_usd}
                     onChange={(e) => set('min_monthly_saving_usd', Number(e.target.value))} className={inputClass} />
            </Field>
            <Field label="Min samples" hint="Fewer observations than this means no recommendation.">
              <input type="number" min={1} step={1} value={policy.min_samples}
                     onChange={(e) => set('min_samples', Number(e.target.value))} className={inputClass} />
            </Field>
            <Field label="Stale after (h)" hint="Older metrics than this need a human.">
              <input type="number" min={1} step={1} value={policy.stale_after_hours}
                     onChange={(e) => set('stale_after_hours', Number(e.target.value))} className={inputClass} />
            </Field>
            <Field label="Top N findings" hint="How many opportunities the report ranks.">
              <input type="number" min={1} max={50} step={1} value={policy.top_n_findings}
                     onChange={(e) => set('top_n_findings', Number(e.target.value))} className={inputClass} />
            </Field>
          </div>
        </section>

        <section className="space-y-3" aria-label="Floors">
          <h3 className="text-sm font-semibold">Floors</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="CPU p99 floor ×" hint="A proposal may not fall below this multiple of CPU p99.">
              <input type="number" min={1} max={3} step={0.05} value={policy.cpu_floor_p99_multiplier}
                     onChange={(e) => set('cpu_floor_p99_multiplier', Number(e.target.value))} className={inputClass} />
            </Field>
            <Field label="Memory p99 floor ×" hint="A proposal may not fall below this multiple of memory p99.">
              <input type="number" min={1} max={3} step={0.05} value={policy.memory_floor_p99_multiplier}
                     onChange={(e) => set('memory_floor_p99_multiplier', Number(e.target.value))} className={inputClass} />
            </Field>
            <Field label="Min CPU request (m)" hint="An absolute floor, whatever the p99 says.">
              <input type="number" min={0} step={10} value={policy.min_cpu_request_millicores}
                     onChange={(e) => set('min_cpu_request_millicores', Number(e.target.value))} className={inputClass} />
            </Field>
            <Field label="Min memory request (MiB)" hint="An absolute floor, whatever the p99 says.">
              <input type="number" min={0} step={64} value={policy.min_memory_request_mib}
                     onChange={(e) => set('min_memory_request_mib', Number(e.target.value))} className={inputClass} />
            </Field>
          </div>
        </section>

        <section className="space-y-3" aria-label="Events and change windows">
          <h3 className="text-sm font-semibold">Events and change windows</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Risk window (h)" hint="How far ahead an event is considered.">
              <input type="number" min={1} step={1} value={policy.risk_window_hours}
                     onChange={(e) => set('risk_window_hours', Number(e.target.value))} className={inputClass} />
            </Field>
            <Field label="Event freeze (h)" hint="Keep deferring this long after a high-impact event ends.">
              <input type="number" min={0} step={1} value={policy.event_freeze_hours_after}
                     onChange={(e) => set('event_freeze_hours_after', Number(e.target.value))} className={inputClass} />
            </Field>
            <Field label="Change window start (h)" hint="Earliest hour of day a change may be proposed.">
              <input type="number" min={0} max={24} step={1} value={policy.change_window_start_hour}
                     onChange={(e) => set('change_window_start_hour', Number(e.target.value))} className={inputClass} />
            </Field>
            <Field label="Change window end (h)" hint="Latest hour of day a change may be proposed.">
              <input type="number" min={0} max={24} step={1} value={policy.change_window_end_hour}
                     onChange={(e) => set('change_window_end_hour', Number(e.target.value))} className={inputClass} />
            </Field>
          </div>
          <fieldset>
            <legend className="text-xs font-medium">Change window days</legend>
            <div className="mt-1.5 flex flex-wrap gap-3">
              {WEEKDAYS.map((day, index) => (
                <label key={day} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={policy.change_window_days.includes(index)}
                    onChange={(e) => set(
                      'change_window_days',
                      e.target.checked
                        ? [...policy.change_window_days, index].sort((a, b) => a - b)
                        : policy.change_window_days.filter((d) => d !== index),
                    )}
                  />
                  {day}
                </label>
              ))}
            </div>
            <span className="mt-1 block text-xs text-muted-foreground">None selected means any day is allowed.</span>
          </fieldset>
        </section>

        <section className="space-y-3" aria-label="Headroom by criticality">
          <h3 className="text-sm font-semibold">Headroom by criticality</h3>
          {Object.keys(policy.criticality_headroom).length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No criticality headroom is set. Every workload is treated the same way.
            </p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(policy.criticality_headroom).map(([key, value]) => (
                <Field key={key} label={`${key} ×`} hint="Extra headroom over p99 for this criticality.">
                  <input
                    type="number"
                    min={1}
                    max={3}
                    step={0.05}
                    value={value}
                    onChange={(e) => set('criticality_headroom', {
                      ...policy.criticality_headroom,
                      [key]: Number(e.target.value),
                    })}
                    className={inputClass}
                  />
                </Field>
              ))}
            </div>
          )}
        </section>

        <section className="space-y-3" aria-label="Workload lists">
          <h3 className="text-sm font-semibold">Workload lists</h3>
          <Field label="Protected workloads" hint="Comma-separated. Reductions on these are blocked outright.">
            <input value={policy.protected_workloads.join(', ')} onChange={(e) => set('protected_workloads',
              e.target.value.split(',').map((s) => s.trim()).filter(Boolean))} className={inputClass} />
          </Field>

          <Field label="Excluded workloads" hint="Comma-separated. Never optimised — these report no_change.">
            <input value={policy.excluded_workloads.join(', ')} onChange={(e) => set('excluded_workloads',
              e.target.value.split(',').map((s) => s.trim()).filter(Boolean))} className={inputClass} />
          </Field>
        </section>

        {!!policy.policy_exceptions.length && (
          <section className="space-y-2 rounded-md border p-3">
            <h4 className="text-sm font-medium">Policy exceptions</h4>
            <ul className="space-y-1 text-xs">
              {policy.policy_exceptions.map((ex) => (
                <li key={`${ex.workload_id}-${ex.expires_at}`} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{ex.workload_id}</span>
                  <span className="text-muted-foreground">{ex.reason}</span>
                  <span className="text-muted-foreground">· expires {new Date(ex.expires_at).toLocaleDateString()}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          <Button size="sm" onClick={() => void save()} disabled={!dirty || busy}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}Save new version
          </Button>
          <Button size="sm" variant="ghost" onClick={() => { setPolicy(original); }} disabled={!dirty || busy}>
            <RotateCcw aria-hidden />Discard changes
          </Button>
          <Button size="sm" variant="ghost" onClick={resetToDefaults} disabled={!defaults || busy}>
            <RotateCcw aria-hidden />Reset to defaults
          </Button>
          <span className={cn('text-xs', dirty ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground')}>
            {dirty ? 'Unsaved changes' : 'No changes'}
          </span>
          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
            <Lock className="size-3" aria-hidden />Policy history is append-only
          </span>
        </div>
      </CardContent>
    </Card>
  )
}
