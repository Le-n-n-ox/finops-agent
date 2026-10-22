import { History, LayoutDashboard, Landmark, ShieldCheck } from 'lucide-react'
import { cn } from '@/lib/utils'

export type View = 'analysis' | 'policy' | 'history'

const ITEMS: { key: View; label: string; icon: typeof LayoutDashboard; hint: string }[] = [
  { key: 'analysis', label: 'Analysis', icon: LayoutDashboard, hint: 'Findings, savings and evidence' },
  { key: 'policy', label: 'Policy', icon: ShieldCheck, hint: 'Thresholds the optimizer applies' },
  { key: 'history', label: 'History', icon: History, hint: 'Past decisions and their audit trail' },
]

interface Props {
  view: View
  onViewChange: (view: View) => void
  /** Called after a link is picked. The mobile drawer uses it to close itself. */
  onNavigate?: () => void
  className?: string
  /** Set on the desktop rail so the collapse button can point at what it controls. */
  id?: string
  /**
   * When set, the nav shows icons only and the labels move into the buttons' tooltips. The
   * mobile drawer never uses this: a drawer is already off-screen until it is asked for, so
   * hiding its labels there would only make it harder to read.
   */
  collapsed?: boolean
  /**
   * Opens the landing page. It is not one of the sections — it is the front door, so it sits
   * above them and is separated from them.
   */
  onOverview?: () => void
}

/**
 * The section nav. It is rendered twice: once as the permanent rail on wide screens and once
 * inside the mobile drawer. Both copies drive the same `view` state, so they can never disagree.
 */
export default function Sidebar({ view, onViewChange, onNavigate, className, id, collapsed = false, onOverview }: Props) {
  return (
    <nav id={id} className={cn('flex flex-col gap-1', className)} aria-label="Sections">
      {onOverview && (
        <>
          <button
            onClick={() => { onOverview(); onNavigate?.() }}
            aria-label={collapsed ? 'Overview' : undefined}
            title={collapsed ? 'Overview' : 'What this system does'}
            className={cn(
              'group flex items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-accent-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50',
              collapsed && 'justify-center px-0',
            )}
          >
            <Landmark className="size-4 shrink-0 group-hover:text-accent-foreground" aria-hidden />
            {!collapsed && <span className="truncate">Overview</span>}
          </button>
          <div className="my-1 border-t" role="presentation" />
        </>
      )}
      {ITEMS.map(({ key, label, icon: Icon, hint }) => {
        const active = view === key
        return (
          <button
            key={key}
            onClick={() => { onViewChange(key); onNavigate?.() }}
            aria-current={active ? 'page' : undefined}
            // Collapsed, the label is only in the tooltip, so it has to be the accessible name too.
            aria-label={collapsed ? label : undefined}
            title={collapsed ? label : hint}
            className={cn(
              'group flex items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
              collapsed && 'justify-center px-0',
              active
                ? 'bg-primary/10 text-primary'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
            )}
          >
            <Icon className={cn('size-4 shrink-0', active ? 'text-primary' : 'text-muted-foreground group-hover:text-accent-foreground')} aria-hidden />
            {!collapsed && <span className="truncate">{label}</span>}
            {active && !collapsed && <span className="ml-auto size-1.5 rounded-full bg-primary" aria-hidden />}
          </button>
        )
      })}
    </nav>
  )
}
