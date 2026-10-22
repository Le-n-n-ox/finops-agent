import PolicyPanel from '@/components/PolicyPanel'
import { useAnalysis } from '@/state/analysis-context'

/** Policy: the safety rules the critic enforces, editable. */
export default function PolicyPage() {
  const { reload } = useAnalysis()
  return <PolicyPanel onSaved={() => void reload()} />
}
