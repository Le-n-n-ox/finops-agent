import { useEffect, useRef } from 'react'
import DecisionDonut from '@/components/DecisionDonut'
import DetailPanel from '@/components/DetailPanel'
import DetailSheet from '@/components/DetailSheet'
import ResultsTable from '@/components/ResultsTable'
import SavingsChart from '@/components/SavingsChart'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { useAnalysis } from '@/state/analysis-context'
import { useRouter } from '@/state/router-context'

/**
 * Workloads: the findings, and the evidence behind each one.
 *
 * The table is the list; the panel on the right is the drill-down. On a phone the panel becomes a
 * bottom sheet, because a side-by-side layout on a narrow screen is unreadable.
 *
 * The selected workload is in the URL, so "look at this one" is a link you can paste to someone
 * and they land on the same evidence you are looking at.
 */
export default function Workloads() {
  const { state, filter, setFilter, selectedId, setSelectedId, workloadRows, simulatorUnavailable } = useAnalysis()
  const { navigate, search } = useRouter()
  const isDesktop = useMediaQuery('(min-width: 1024px)')

  // The URL and the open workload are one thing, kept in step by the effect below.
  //
  // `lastWritten` remembers the query this page last wrote, so the effect can tell two cases
  // apart. A URL that still matches it means the selection moved underneath it and the URL is
  // stale - the provider clears the selection when a new run replaces the old one, and the
  // query has to be cleared with it. Any other URL moved on its own: the back button, a pasted
  // link, a link from a colleague - and the selection follows it.
  const lastWritten = useRef<string | null>(null)

  useEffect(() => {
    const param = new URLSearchParams(search).get('workload')
    if (param === lastWritten.current) {
      if (param !== selectedId) {
        const query = selectedId ? `?workload=${encodeURIComponent(selectedId)}` : ''
        lastWritten.current = selectedId
        navigate(`/workloads${query}`, { replace: true })
      }
      return
    }
    if (param !== selectedId) setSelectedId(param)
    // `selectedId` is deliberately not a dependency: this effect reacts to the URL moving, and
    // a selection change is handled by the branch above. Adding it would make the two fight.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, navigate])

  if (!state) return null

  const visible = state.data.results.filter((r) => filter === 'all' || r.decision === filter)
  const selected = state.data.results.find((r) => r.workload_id === selectedId) ?? null
  // A link to a workload that is not in this run is a stale link, not an empty panel: say so,
  // so a reviewer who pastes one can tell a broken link from a broken app.
  const missing = selectedId !== null && !selected

  const select = (id: string | null) => {
    setSelectedId(id)
    const query = id ? `?workload=${encodeURIComponent(id)}` : ''
    lastWritten.current = id
    // Pushed, not replaced: the back button is the reason to route at all, and a reviewer who
    // opens a workload and goes back should land on the list, not leave the page.
    navigate(`/workloads${query}`)
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-2">
        <DecisionDonut summary={state.data.summary} active={filter} onFilter={setFilter} />
        <SavingsChart results={state.data.results} />
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[1fr_440px]">
        <ResultsTable results={visible} selectedId={selectedId} onSelect={select} workloadRows={workloadRows} />
        {isDesktop && (selected ? (
          <DetailPanel
            key={selected.workload_id}
            result={selected}
            reportId={state.data.analysis_id}
            simulatorUnavailable={simulatorUnavailable}
          />
        ) : (
          <p className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
            {missing
              ? `“${selectedId}” is not in this analysis. It may belong to an earlier run - run the analysis again, or pick a workload from the list.`
              : 'Select a workload to see evidence, the critic’s audit trail and the proposed patch.'}
          </p>
        ))}
      </div>

      {!isDesktop && selected && (
        <DetailSheet
          result={selected}
          reportId={state.data.analysis_id}
          onClose={() => select(null)}
          simulatorUnavailable={simulatorUnavailable}
        />
      )}
    </div>
  )
}
