import { useEffect } from 'react'
import { toast } from 'sonner'
import { FileDown, FileJson2, History, Info, Lock, Printer, RefreshCw, ServerCog, ShieldCheck, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { buildReport, downloadText } from '@/lib/report'
import AppToaster from '@/components/AppToaster'
import ThemeToggle from '@/components/ThemeToggle'
import ScenarioSwitcher from '@/components/ScenarioSwitcher'
import ProvenanceStrip from '@/components/ProvenanceStrip'
import { useAnalysis } from '@/state/analysis-context'
import { useRouter } from '@/state/router-context'
import type { AnalysisResponse } from '@/types'
import Overview from '@/pages/Overview'
import Workloads from '@/pages/Workloads'
import Evidence from '@/pages/Evidence'
import PolicyPage from '@/pages/PolicyPage'
import HistoryPage from '@/pages/HistoryPage'

function LoadingSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading analysis">
      <Skeleton className="h-20" />
      <Skeleton className="h-32" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div>
      <Skeleton className="h-64" />
    </div>
  )
}

/**
 * What ran, said in words the reader can act on.
 *
 * The badge must never imply a language model ran when it did not: a reviewer who believes a
 * model was called reads a different kind of trust into the objections than the code supports.
 * So the live case names the model, and the stand-in case says so plainly.
 *
 * Three outcomes, not two, because "the stand-in answered" and "nothing is recorded about
 * which reasoner answered" are different facts. A report stored before the field existed, and
 * the bundled mock fixtures, have no `llm_backend` at all - neither of them is a stand-in run,
 * and neither may be described as one.
 */
function modelBadge(data: AnalysisResponse): { text: string; live: boolean; title: string } {
  if (data.llm_backend === 'openai-compatible') {
    return {
      text: data.llm_model ?? 'live model',
      live: true,
      title: `Language model ${data.llm_model ?? ''} answered the agent turns.`.trim(),
    }
  }
  if (data.llm_backend === 'simulated') {
    return {
      text: 'no live model (deterministic stand-in)',
      live: false,
      title: 'The model server was not reachable, so the deterministic stand-in answered the agent turns. No language model ran.',
    }
  }
  return {
    text: 'no live model (not recorded)',
    live: false,
    title: 'This response does not record which reasoner answered, so no language model is claimed to have run.',
  }
}

/**
 * The one reasoning path. The response's `mode` field still describes the run (for example
 * "demo" when the fixed demo clock is in use), but the path itself is always the agent cycle.
 */
const REASONING_PATH = 'agent cycle'

const PAGES = [
  { path: '/', label: 'Overview', icon: ShieldCheck },
  { path: '/workloads', label: 'Workloads', icon: ServerCog },
  { path: '/evidence', label: 'Evidence', icon: Info },
  { path: '/policy', label: 'Policy', icon: Lock },
  { path: '/history', label: 'History', icon: History },
] as const

export default function App() {
  const { state, error, loading, scenario, setScenario, reload, llmStatus } = useAnalysis()
  const { path, navigate } = useRouter()

  const exportReport = async (format: 'markdown' | 'json') => {
    if (!state) return
    const extension = format === 'markdown' ? 'md' : 'json'
    const filename = `finops-audit-report-${state.data.analysis_id}.${extension}`
    try {
      // Export the analysis that is ON SCREEN. Fetching a fresh report would hand the reviewer a
      // document describing a run they never looked at, which defeats the point of an audit trail.
      if (state.source === 'api') {
        const response = await fetch(`/api/report?format=${format}&report_id=${encodeURIComponent(state.data.analysis_id)}`)
        if (!response.ok) throw new Error(`Report API ${response.status}`)
        const content = format === 'markdown' ? await response.text() : JSON.stringify(await response.json(), null, 2)
        downloadText(filename, content, format === 'markdown' ? 'text/markdown' : 'application/json')
      } else if (format === 'markdown') {
        downloadText(filename, buildReport(state.data), 'text/markdown')
      } else {
        downloadText(filename, JSON.stringify(state.data, null, 2), 'application/json')
      }
      toast.success(`Report saved as ${filename}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not export audit report')
    }
  }

  // An unknown path is a stale link, not an error: send it to the overview rather than a 404.
  const known = PAGES.some((p) => p.path === path)
  const active = known ? path : '/'

  useEffect(() => {
    if (!known) navigate('/', { replace: true })
  }, [known, navigate])

  // The badge names what actually ran. It must never imply a language model ran when it did not:
  // a reviewer who believes a model was called reads a different kind of trust into the
  // objections than the code supports.
  const badge = state
    ? state.source === 'api'
      ? (() => {
          const m = modelBadge(state.data)
          return { text: `Live API · ${REASONING_PATH} · ${m.text}`, live: m.live, title: m.title }
        })()
      : { text: 'Mock data · API offline · no live model', live: false, title: 'Bundled fixtures, not a backend run.' }
    : llmStatus
      ? {
          text: llmStatus.backend === 'openai-compatible'
            ? `Model server · ${llmStatus.model ?? 'live model'}`
            : 'Model server unavailable · deterministic stand-in',
          live: llmStatus.backend === 'openai-compatible',
          title: llmStatus.detail ?? 'The model server has not been contacted yet.',
        }
      : null

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground"><ServerCog className="size-5" aria-hidden /></span>
          <div>
            <h1 className="text-xl leading-tight font-semibold">Kubernetes FinOps Agent</h1>
            <p className="text-sm text-muted-foreground">Evidence-based, multi-agent resource recommendations</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline"><Lock aria-hidden />Recommendation-only</Badge>
          {badge && (
            <Badge
              variant="outline"
              className={cn(
                badge.live
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300'
                  : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200',
              )}
              title={badge.title}
            >
              {badge.text}
            </Badge>
          )}
          {state?.source === 'mock' && <ScenarioSwitcher value={scenario} onChange={setScenario} />}
          <div className="flex items-center gap-2 print:hidden">
            <Button variant="outline" size="icon" onClick={() => void exportReport('markdown')} disabled={!state} aria-label="Export report as Markdown" title="Export report (Markdown)"><FileDown /></Button>
            <Button variant="outline" size="icon" onClick={() => void exportReport('json')} disabled={!state} aria-label="Export audit data as JSON" title="Export audit data (JSON)"><FileJson2 /></Button>
            <Button variant="outline" size="icon" onClick={() => window.print()} disabled={!state} aria-label="Print or save as PDF" title="Print / save as PDF"><Printer /></Button>
            <ThemeToggle />
            <Button onClick={() => void reload()} disabled={loading}>
              <RefreshCw className={cn(loading && 'animate-spin')} aria-hidden />{loading ? 'Running…' : 'Run analysis'}
            </Button>
          </div>
        </div>
      </header>

      {error && (
        <p role="alert" className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          <TriangleAlert className="size-4 shrink-0" aria-hidden />{error}
        </p>
      )}
      {loading && !state && <LoadingSkeleton />}

      {/*
        The navigation is outside the analysis block on purpose. Policy and History do not need
        an analysis - the policy editor fetches its own policy and the history page its own
        decisions - so a failed analysis must not take them out of reach. The pages that do need
        the analysis already render nothing when it is missing.
      */}
      <nav className="flex flex-wrap gap-1 border-b print:hidden" aria-label="Sections">
        {PAGES.map(({ path: to, label, icon: Icon }) => (
          <button
            key={to}
            onClick={() => navigate(to)}
            aria-current={active === to ? 'page' : undefined}
            className={cn(
              'flex items-center gap-1.5 px-3 py-2 text-sm font-medium -mb-px border-b-2 transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
              active === to ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            <Icon className="size-4" aria-hidden />{label}
          </button>
        ))}
      </nav>

      {state && (
        <>
          <ProvenanceStrip data={state.data} source={state.source} />

          {state.data.warnings.map((w) => (
            <p key={w} className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
              <Info className="size-4 shrink-0" aria-hidden />{w}
            </p>
          ))}
        </>
      )}

      {active === '/' && <Overview />}
      {active === '/workloads' && <Workloads />}
      {active === '/evidence' && <Evidence />}
      {active === '/policy' && <PolicyPage />}
      {active === '/history' && <HistoryPage />}

      <footer className="border-t pt-4 text-xs text-muted-foreground">
        Prototype using local/mock data. Savings are illustrative estimates, not guaranteed bill reductions. Every change requires human approval; nothing is applied to a cluster.
      </footer>

      <AppToaster />
    </div>
  )
}
