import { CheckCircle2, Clock, Eye, MinusCircle, XCircle, type LucideIcon } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { CheckStatus, DecisionStatus, RiskLevel } from '@/types'

export const DECISIONS: Record<DecisionStatus, { label: string; icon: LucideIcon; badge: string; accent: string; hex: string }> = {
  approved: { label: 'Approved', icon: CheckCircle2, badge: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300', accent: 'text-emerald-600 dark:text-emerald-400', hex: '#10b981' },
  deferred: { label: 'Deferred', icon: Clock, badge: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300', accent: 'text-amber-600 dark:text-amber-400', hex: '#f59e0b' },
  rejected: { label: 'Rejected', icon: XCircle, badge: 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300', accent: 'text-red-600 dark:text-red-400', hex: '#ef4444' },
  needs_review: { label: 'Needs review', icon: Eye, badge: 'border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-300', accent: 'text-indigo-600 dark:text-indigo-400', hex: '#6366f1' },
  no_change: { label: 'No change', icon: MinusCircle, badge: 'border-border bg-muted text-muted-foreground', accent: 'text-muted-foreground', hex: '#94a3b8' },
}

export function DecisionBadge({ decision }: { decision: DecisionStatus }) {
  const { label, icon: Icon, badge } = DECISIONS[decision]
  return <Badge variant="outline" className={badge}><Icon aria-hidden />{label}</Badge>
}

const RISK: Record<RiskLevel, string> = {
  low: 'text-emerald-700 dark:text-emerald-400',
  medium: 'text-amber-700 dark:text-amber-400',
  high: 'text-red-700 dark:text-red-400',
}

export function RiskText({ risk, className }: { risk: RiskLevel; className?: string }) {
  return <span className={cn('font-medium capitalize', RISK[risk], className)}>{risk}</span>
}

export const CHECK_STYLE: Record<CheckStatus, string> = {
  passed: 'bg-emerald-500',
  triggered: 'bg-red-500',
  skipped: 'bg-muted-foreground/40',
}