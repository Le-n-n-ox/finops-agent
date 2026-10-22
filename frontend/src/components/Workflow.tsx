import {
  ChevronRight,
  Database,
  FileText,
  Gavel,
  Search,
  ShieldQuestion,
  type LucideIcon,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
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
 * they are the safety model behind the Critic and Judge phases, not a separate path. Drawing the
 * old five-stage deterministic pipeline here would show stages that did not run.
 *
 * It is drawn as a path rather than a list: a rail runs behind the stages and each stage hangs
 * off it, so the direction of travel is visible before anything is read.
 */
export default function Workflow({ data }: { data: AnalysisResponse }) {
  const proposed = data.results.filter((r) => r.proposal.status === 'proposed').length
  const challenged = data.results.filter((r) => r.checks.some((c) => c.status === 'triggered')).length
  const objections = data.results.reduce((n, r) => n + (r.objections?.length ?? 0), 0)
  const toolCalls = data.results.reduce((n, r) => n + (r.cycles ?? []).reduce((m, c) => m + c.steps.length, 0), 0)

  const detail = [
    `${data.summary.workloads_evaluated} workloads`,
    `${proposed} proposals · ${toolCalls} tool calls`,
    `${objections} objections · ${challenged} challenged`,
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

          {AGENT_STAGES.map(({ icon: Icon, title, agent }, i) => (
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

              {i < AGENT_STAGES.length - 1 && (
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
