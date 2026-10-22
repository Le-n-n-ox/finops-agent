import { ChevronRight, Database, FileText, Gavel, Search, ShieldQuestion, type LucideIcon } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import type { AnalysisResponse } from '@/types'

const AGENT_STAGES: { icon: LucideIcon; title: string; agent: string }[] = [
    { icon: Database, title: 'Collect data', agent: 'Data Collector' },
    { icon: Search, title: 'Gather evidence', agent: 'Proposer' },
    { icon: ShieldQuestion, title: 'Red-team', agent: 'Adversarial Critic' },
    { icon: Gavel, title: 'Rule on it', agent: 'Judge' },
    { icon: FileText, title: 'Report', agent: 'Report Generator' },
]

/**
 * The review cycle the analysis actually ran, in order.
 *
 * There is one reasoning path now - the Proposer, the adversarial Critic and the Judge - so this
 * is always the agent cycle. The deterministic optimizer and critic still own every final status;
 * they are the safety model behind the Critic and Judge phases, not a separate path.
 */
export default function Workflow({ data }: { data: AnalysisResponse }) {
    const proposed = data.results.filter((r) => r.proposal.status === 'proposed').length
    const challenged = data.results.filter((r) => r.checks.some((c) => c.status === 'triggered')).length
    const objections = data.results.reduce((n, r) => n + (r.objections?.length ?? 0), 0)
    const toolCalls = data.results.reduce((n, r) => n + (r.cycles ?? []).reduce((m, c) => m + c.steps.length, 0), 0)

    const detail = [
        `${data.summary.workloads_evaluated} workloads`,
        `${proposed} proposals · ${toolCalls} tool calls`,
        `${objections} objection(s) · ${challenged} challenged`,
        `${data.summary.workloads_evaluated} decisions`,
        `${data.results.filter((r) => r.yaml_patch).length} patches`,
    ]

    return (
        <Card className="py-4">
            <CardContent>
                <ol className="flex flex-wrap items-center gap-x-2 gap-y-3">
                    {AGENT_STAGES.map(({ icon: Icon, title, agent }, i) => (
                        <li key={title} style={{ animationDelay: `${i * 70}ms` }} className="flex items-center gap-2 animate-in fade-in slide-in-from-left-2 duration-300 fill-mode-both motion-reduce:animate-none">
                            <div className="flex items-center gap-3 rounded-lg border bg-background px-3 py-2">
                                <span className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground"><Icon className="size-4" aria-hidden /></span>
                                <div>
                                    <p className="text-sm leading-tight font-medium">{i + 1}. {title}</p>
                                    <p className="text-xs text-muted-foreground">{agent} · {detail[i]}</p>
                                </div>
                            </div>
                            {i < AGENT_STAGES.length - 1 && <ChevronRight className="size-4 text-muted-foreground" aria-hidden />}
                        </li>
                    ))}
                </ol>
            </CardContent>
        </Card>
    )
}
