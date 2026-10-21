import type { AnalysisResponse } from '@/types'

export interface LoadResult {
  data: AnalysisResponse
  source: 'api' | 'mock'
}

export interface ScenarioInfo { id: string; label: string; description: string }

/**
 * Try POST /api/analyze; fall back to bundled fixtures so the UI works before the backend does.
 * `scenario` is sent to the API (ignored until backend supports it) and selects the mock fixture.
 */
export async function runAnalysis(scenario = 'all', mode = 'pipeline'): Promise<LoadResult> {
  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario, mode }),
    })
    if (!res.ok) throw new Error(`API ${res.status}`)
    return { data: (await res.json()) as AnalysisResponse, source: 'api' }
  } catch {
    const safe = /^[a-z-]+$/.test(scenario) ? scenario : 'all'
    const res = await fetch(safe === 'all' ? '/mock/analysis.json' : `/mock/scenarios/${safe}.json`)
    if (!res.ok) throw new Error('Mock data not found. Run: npm run mock')
    return { data: (await res.json()) as AnalysisResponse, source: 'mock' }
  }
}

export async function loadScenarios(): Promise<ScenarioInfo[]> {
  try {
    const res = await fetch('/mock/scenarios.json')
    return res.ok ? ((await res.json()) as ScenarioInfo[]) : []
  } catch {
    return []
  }
}