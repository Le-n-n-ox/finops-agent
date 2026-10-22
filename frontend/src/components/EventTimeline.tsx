import { useState } from 'react'
import { CalendarClock, ChevronRight, TriangleAlert } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { EventRow } from '@/types'

/**
 * Business events, and the workloads they put at risk.
 *
 * A deferred recommendation is much easier to accept when you can see the campaign that caused it
 * and which other services it touches. The event list is the context behind the critic's decisions.
 */

const RISK_STYLE: Record<string, string> = {
  high: 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300',
  medium: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300',
  low: 'border-border bg-muted text-muted-foreground',
}

const fmtRange = (start: string, end: string) => {
  const s = new Date(start)
  const e = new Date(end)
  const sameDay = s.toDateString() === e.toDateString()
  const day = s.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
  const time = (d: Date) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  return sameDay ? `${day}, ${time(s)}–${time(e)}` : `${day} ${time(s)} → ${e.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${time(e)}`
}

export default function EventTimeline({ events, now }: { events: EventRow[]; now?: string }) {
  // The reference time is fixed at mount. Recomputing it on every render would make an event
  // flicker between "live" and "past" while the page is open.
  const [reference] = useState(() => (now ? new Date(now) : new Date()))
  const [expanded, setExpanded] = useState<string | null>(null)

  if (!events.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Business events</CardTitle>
          <CardDescription>Campaigns and freezes that affect reduction decisions</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            No business events are configured.
          </p>
        </CardContent>
      </Card>
    )
  }

  const withState = events.map((e) => {
    const start = new Date(e.start_at)
    const end = new Date(e.end_at)
    const live = reference >= start && reference <= end
    const upcoming = start > reference
    return { ...e, live, upcoming, past: end < reference }
  })

  const live = withState.filter((e) => e.live)
  const upcoming = withState.filter((e) => e.upcoming)
  const past = withState.filter((e) => e.past)

  const Row = ({ e }: { e: typeof withState[number] }) => {
    const isOpen = expanded === e.event_id
    return (
      <li className="border-b last:border-b-0">
        <button
          type="button"
          onClick={() => setExpanded(isOpen ? null : e.event_id)}
          aria-expanded={isOpen}
          className="flex w-full items-start gap-2 py-2 text-left outline-none hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <ChevronRight className={cn('mt-1 size-3.5 shrink-0 text-muted-foreground transition-transform', isOpen && 'rotate-90')} aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{e.name}</span>
              {e.live && (
                <span className="rounded border border-red-300 bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
                  LIVE NOW
                </span>
              )}
              {e.upcoming && <span className="rounded border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">UPCOMING</span>}
              <span className={cn('rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase', RISK_STYLE[e.risk?.toLowerCase()] ?? RISK_STYLE.low)}>
                {e.risk || 'unknown'} risk
              </span>
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">{fmtRange(e.start_at, e.end_at)}</span>
            {isOpen && (
              <span className="mt-1.5 block space-y-1">
                {e.notes && <span className="block text-xs">{e.notes}</span>}
                {e.expected_traffic && <span className="block text-xs text-muted-foreground">Expected traffic: {e.expected_traffic}</span>}
                {!!e.services.length && (
                  <span className="mt-1 flex flex-wrap gap-1">
                    {e.services.map((s) => (
                      <span key={s} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{s}</span>
                    ))}
                  </span>
                )}
              </span>
            )}
          </span>
        </button>
      </li>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarClock className="size-5 text-muted-foreground" aria-hidden />Business events
        </CardTitle>
        <CardDescription>
          {live.length > 0 && (
            <span className="font-medium text-red-600 dark:text-red-400">{live.length} live now · </span>
          )}
          {upcoming.length} upcoming · {past.length} past — reductions near an event are deferred
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="max-h-72 overflow-y-auto">
          {[...live, ...upcoming, ...past].map((e) => <Row key={e.event_id} e={e} />)}
        </ul>
        {live.length > 0 && (
          <p className="mt-3 flex items-start gap-1.5 rounded-md border border-red-200 bg-red-50 p-2.5 text-xs text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            A live event freezes reductions on the services it affects. Wait for it to pass before acting.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
