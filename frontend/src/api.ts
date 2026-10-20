import type { AnalysisResponse } from '@/types'

export interface LoadResult {
  data: AnalysisResponse
  source: 'api' | 'mock'
}

/** Try POST /api/analyze; fall back to the bundled sample payload so the UI works before the backend does. */
export async function runAnalysis(): Promise<LoadResult> {
  try {
    const res = await fetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    if (!res.ok) throw new Error(`API ${res.status}`)
    return { data: (await res.json()) as AnalysisResponse, source: 'api' }
  } catch {
    const res = await fetch('/mock/analysis.json')
    if (!res.ok) throw new Error('Mock data not found')
    return { data: (await res.json()) as AnalysisResponse, source: 'mock' }
  }
}