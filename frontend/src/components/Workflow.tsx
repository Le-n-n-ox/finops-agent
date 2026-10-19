import { Calculator, ChevronRight, Database, FileText, Scale, ShieldAlert, type LucideIcon } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import type { AnalysisResponse } from '@/types'

const STAGES: { icon: LucideIcon; title: string; agent: string }[] = [
    { icon: Database, title: 'Collect data', agent: 'Data Collector' },
    { icon: Calculator, title: 'Estimate waste', agent: 'FinOps Optimizer' },
    { icon: ShieldAlert, title: 'Critique risk', agent: 'Context Critic' },
    { icon: Scale, title: 'Decide', agent: 'Approve · defer · reject' },
    { icon: FileText, title: 'Report', agent: 'Report Generator' },
]

export default function Workflow({ data }: { data: AnalysisResponse }) {
    const proposed = data.results.filter((r) => r.proposal.status === 'proposed').length
    const challenged = data.results.filter((r) => r.checks.some((c) => c.status === 'triggered')).length
    const detail = [
        `${data.summary.workloads_evaluated} workloads`,
        `${proposed} proposals`,
        `${challenged} challenged`,
        `${data.summary.workloads_evaluated} decisions`,
        `${data.results.filter((r) => r.yaml_patch).length} patches`,
    ]
    return (
        <Card className="py-4">
            <CardContent>
                <ol className="flex flex-wrap items-center gap-x-2 gap-y-3">
                    {STAGES.map(({ icon: Icon, title, agent }, i) => (
                        <li key={title} style={{ animationDelay: `${i * 70}ms` }} className="flex items-center gap-2 animate-in fade-in slide-in-from-left-2 duration-300 fill-mode-both motion-reduce:animate-none">
                            <div className="flex items-center gap-3 rounded-lg border bg-background px-3 py-2">
                                <span className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground"><Icon className="size-4" aria-hidden /></span>
                                <div>
                                    <p className="text-sm leading-tight font-medium">{i + 1}. {title}</p>
                                    <p className="text-xs text-muted-foreground">{agent} · {detail[i]}</p>
                                </div>
                            </div>
                            {i < STAGES.length - 1 && <ChevronRight className="size-4 text-muted-foreground" aria-hidden />}
                        </li>
                    ))}
                </ol>
            </CardContent>
        </Card>
    )
}