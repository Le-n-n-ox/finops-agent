import type { Ref } from 'react'
import { FileDown, FileJson2, Lock, Menu, Printer, RefreshCw, ServerCog } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import ScenarioSwitcher from '@/components/ScenarioSwitcher'
import ThemeToggle from '@/components/ThemeToggle'
import { cn } from '@/lib/utils'

export interface ToolbarProps {
  /** Which backend the last run came from, or null before the first run lands. */
  source: 'api' | 'mock' | null
  modeLabel: string
  /**
   * Which reasoner answered the agent's turns, or null before anything has been produced.
   *
   * There is no mode switch here. The agent cycle is the only reasoning path - the deterministic
   * optimizer and critic are the safety model behind every final decision, not an alternative -
   * so a switch between them would promise a difference the backend does not make. What is
   * worth showing is which reasoner actually answered: a live language model, the deterministic
   * stand-in, or nothing recorded.
   */
  modelBadge: { text: string; live: boolean; title: string } | null
  scenario: string
  onScenarioChange: (id: string) => void
  loading: boolean
  onRun: () => void
  canExport: boolean
  onExport: (format: 'markdown' | 'json') => void
  /**
   * `row` is the desktop bar, `stack` is the mobile drawer, `compact` is the phone-sized bar
   * that keeps only the one control worth having within thumb reach.
   */
  layout?: 'row' | 'stack' | 'compact'
}

/**
 * The controls shared by the top bar and the mobile drawer. Both surfaces drive the same state,
 * so a change made in one is reflected in the other.
 */
export function Toolbar({
  source, modeLabel, modelBadge, scenario, onScenarioChange, loading, onRun, canExport, onExport, layout = 'row',
}: ToolbarProps) {
  if (layout === 'compact') {
    return (
      <div className="flex items-center gap-2">
        <Button onClick={onRun} disabled={loading} aria-label="Run analysis">
          <RefreshCw className={cn(loading && 'animate-spin')} aria-hidden />
          <span className="hidden sm:inline">{loading ? 'Running…' : 'Run analysis'}</span>
        </Button>
      </div>
    )
  }

  const stack = layout === 'stack'
  return (
    <div className={cn(stack ? 'flex flex-col gap-3' : 'flex flex-wrap items-center gap-2')}>
      <div className={cn(stack ? 'flex flex-col items-start gap-2' : 'flex flex-wrap items-center gap-2')}>
        <Badge variant="outline"><Lock aria-hidden />Recommendation-only</Badge>
        {source && (
          <Badge variant="outline" className={cn(source === 'api' && 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300')}>
            {source === 'api' ? `Live API · ${modeLabel}` : 'Mock data · API offline'}
          </Badge>
        )}
        {source === 'mock' && <ScenarioSwitcher value={scenario} onChange={onScenarioChange} />}
      </div>

      {modelBadge && (
        <Badge
          variant="outline"
          className={cn(
            modelBadge.live
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300'
              : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200',
          )}
          title={modelBadge.title}
        >
          {modelBadge.text}
        </Badge>
      )}

      <div className={cn('print:hidden', stack ? 'flex flex-col gap-2' : 'flex items-center gap-2')}>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={() => onExport('markdown')} disabled={!canExport} aria-label="Export report as Markdown" title="Export report (Markdown)"><FileDown /></Button>
          <Button variant="outline" size="icon" onClick={() => onExport('json')} disabled={!canExport} aria-label="Export audit data as JSON" title="Export audit data (JSON)"><FileJson2 /></Button>
          <Button variant="outline" size="icon" onClick={() => window.print()} disabled={!canExport} aria-label="Print or save as PDF" title="Print / save as PDF"><Printer /></Button>
          <ThemeToggle />
        </div>
        <Button onClick={onRun} disabled={loading} className={cn(stack && 'w-full justify-center')}>
          <RefreshCw className={cn(loading && 'animate-spin')} aria-hidden />{loading ? 'Running…' : 'Run analysis'}
        </Button>
      </div>
    </div>
  )
}

interface Props extends ToolbarProps {
  /** Opens the mobile drawer that holds the sidebar and the run controls. */
  onOpenNav: () => void
  /** Whether that drawer is currently open, so the button can report it. */
  navOpen?: boolean
  /** The bar's own height is measured so the sidebar can sit exactly below it. */
  ref?: Ref<HTMLElement>
}

/**
 * The top bar. It stays put while the page scrolls, so the run controls and the export buttons
 * are always one click away. On narrow screens the bar keeps only the run button and the rest of
 * the controls move into the drawer, rather than wrapping into a third row.
 */
export default function Navbar({ onOpenNav, navOpen = false, ref, ...toolbar }: Props) {
  return (
    <header ref={ref} className="app-nav sticky top-0 z-40 border-b bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 lg:px-6">
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          onClick={onOpenNav}
          aria-label="Open navigation"
          aria-expanded={navOpen}
          aria-controls="mobile-nav"
        >
          <Menu />
        </Button>

        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <ServerCog className="size-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <h1 className="truncate text-base leading-tight font-semibold">Kubernetes FinOps Agent</h1>
            <p className="hidden truncate text-xs text-muted-foreground sm:block">Evidence-based, multi-agent resource recommendations</p>
          </div>
        </div>

        <div className="ml-auto hidden lg:flex">
          <Toolbar {...toolbar} layout="row" />
        </div>
        <div className="ml-auto lg:hidden">
          <Toolbar {...toolbar} layout="compact" />
        </div>
      </div>
    </header>
  )
}
