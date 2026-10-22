import {
  Calculator,
  ChevronRight,
  Database,
  FileText,
  Gavel,
  Scale,
  Search,
  ShieldAlert,
  ShieldQuestion,
  type LucideIcon,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { AnalysisResponse } from '@/types'

const PIPELINE_STAGES: { icon: LucideIcon; title: string; agent: string }[] = [
  { icon: Database, title: 'Collect data', agent: 'Data Collector' },
  { icon: Calculator, title: 'Estimate waste', agent: 'FinOps Optimizer' },
  { icon: ShieldAlert, title: 'Critique risk', agent: 'Context Critic' },
  { icon: Scale, title: 'Decide', agent: 'Approve · defer · reject' },
  { icon: FileText, title: 'Report', agent: 'Report Generator' },
]

const AGENT_STAGES: { icon: LucideIcon; title: string; agent: string }[] = [
  { icon: Database, title: 'Collect data', agent: 'Data Collector' },
  { icon: Search, title: 'Gather evidence', agent: 'Proposer' },
  { icon: ShieldQuestion, title: 'Red-team', agent: 'Adversarial Critic' },
  { icon: Gavel, title: 'Rule on it', agent: 'Judge' },
  { icon: FileText, title: 'Report', agent: 'Report Generator' },
]

/**
 * The pipeline the analysis actually ran, in order.
 *
 * The two modes do genuinely different work, and showing the deterministic five stages while the
 * agent cycle is running would misrepresent what produced the numbers on screen. In agent mode
 * the middle three stages are the Proposer, the adversarial Critic and the Judge.
 *
 * It is drawn as a path rather than a list: a rail runs behind the stages and each stage hangs
 * off it, so the direction of travel is visible before anything is read.
 */
export default function Workflow({ data }: { data: AnalysisResponse }) {
  const agentMode = data.mode === 'agent' || data.results.some((r) => r.cycles?.length)
  const stages = agentMode ? AGENT_STAGES : PIPELINE_STAGES

  const proposed = data.results.filter((r) => r.proposal.status === 'proposed').length
  const challenged = data.results.filter((r) => r.checks.some((c) => c.status === 'triggered')).length
  const objections = data.results.reduce((n, r) => n + (r.objections?.length ?? 0), 0)
  const toolCalls = data.results.reduce((n, r) => n + (r.cycles ?? []).reduce((m, c) => m + c.steps.length, 0), 0)

  const detail = agentMode
    ? [
        `${data.summary.workloads_evaluated} workloads`,
        `${proposed} proposals · ${toolCalls} tool calls`,
        `${objections} objections · ${challenged} challenged`,
        `${data.summary.workloads_evaluated} decisions`,
        `${data.results.filter((r) => r.yaml_patch).length} patches`,
      ]
    : [
        `${data.summary.workloads_evaluated} workloads`,
        `${proposed} proposals`,
        `${challenged} challenged`,
        `${data.summary.workloads_evaluated} decisions`,
        `${data.results.filter((r) => r.yaml_patch).length} patches`,
      ]

  return (
    <Card className="gap-0 py-0">
      <CardContent className="px-5 py-5">
        <ol className="relative grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {/* The rail: a dashed rule travelling to the right, behind the stages. */}
          <span
            aria-hidden
            className="app-rail-line app-flow absolute inset-x-0 top-[1.35rem] hidden h-px lg:block"
          />

          {stages.map(({ icon: Icon, title, agent }, i) => (
            <li
              key={title}
              className="app-rise relative flex items-center gap-3"
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <span
                aria-hidden
                className={cn(
                  'relative z-10 flex size-11 shrink-0 items-center justify-center rounded-xl',
                  'bg-primary text-primary-foreground ring-4 ring-card',
                )}
              >
                <Icon className="size-5" />
              </span>

              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-muted-foreground tabular-nums">
                  {String(i + 1).padStart(2, '0')}
                </p>
                <p className="truncate text-sm leading-tight font-medium">{title}</p>
                <p className="truncate text-xs text-muted-foreground">{agent}</p>
                <p className="mt-1 truncate text-xs font-medium text-primary tabular-nums">
                  {detail[i]}
                </p>
              </div>

              {i < stages.length - 1 && (
                <ChevronRight
                  aria-hidden
                  className="absolute top-1/2 -right-2 hidden size-4 -translate-y-1/2 text-muted-foreground lg:block"
                />
              )}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  )
}
