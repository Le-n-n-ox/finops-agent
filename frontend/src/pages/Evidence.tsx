import EventTimeline from '@/components/EventTimeline'
import InputStatus from '@/components/InputStatus'
import Workflow from '@/components/Workflow'
import { useAnalysis } from '@/state/analysis-context'

/**
 * Evidence: what this run was built from, and what the critic knew about it.
 *
 * A recommendation is only worth as much as the data behind it. This page shows the stages that
 * ran, the health of every input, and the business events the critic had in front of it — the
 * context behind a "deferred" verdict that is otherwise invisible.
 */
export default function Evidence() {
  const { state, events } = useAnalysis()
  if (!state) return null

  return (
    <div className="space-y-6">
      <Workflow data={state.data} />
      <InputStatus data={state.data} />
      <EventTimeline events={events ?? []} now={state.data.generated_at} />
    </div>
  )
}
