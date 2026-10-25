import { useEffect, useState } from 'react'
import { FlaskConical } from 'lucide-react'
import { loadScenarios, type ScenarioInfo } from '@/api'

interface Props { value: string; onChange: (id: string) => void }

/** Demo mode: loads a focused fixture so a single decision can be shown live. */
export default function ScenarioSwitcher({ value, onChange }: Props) {
  const [items, setItems] = useState<ScenarioInfo[]>([])
  useEffect(() => { void loadScenarios().then(setItems) }, [])
  if (items.length === 0) return null
  return (
    <label className="flex items-center gap-2 text-sm print:hidden">
      <FlaskConical className="size-4 text-muted-foreground" aria-hidden />
      <span className="sr-only">Demo scenario</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-md border bg-background px-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30"
      >
        {items.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
      </select>
    </label>
  )
}