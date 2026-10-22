/**
 * The decision vocabulary of the landing page, in one place.
 *
 * The order is not cosmetic: red and amber next to each other are hard to tell apart under
 * deuteranopia, so the violet sits between them. The steps themselves clear the
 * colour-separation and contrast checks on both the light and the dark surface.
 */

export interface DecisionCounts {
  approved: number
  deferred: number
  needs_review: number
  rejected: number
  no_change: number
}

export type DecisionKey = keyof DecisionCounts

export const DECISION_ORDER: DecisionKey[] = [
  'approved',
  'deferred',
  'needs_review',
  'rejected',
  'no_change',
]

/** The token each decision is drawn with. The steps live in the app's chart tokens. */
export const DECISION_COLOR: Record<DecisionKey, string> = {
  approved: 'var(--chart-approved)',
  deferred: 'var(--chart-deferred)',
  needs_review: 'var(--chart-review)',
  rejected: 'var(--chart-rejected)',
  no_change: 'var(--chart-nochange)',
}

/** How each decision is named in the legend. */
export const DECISION_LABEL: Record<DecisionKey, string> = {
  approved: 'Approved',
  deferred: 'Deferred',
  needs_review: 'Needs review',
  rejected: 'Rejected',
  no_change: 'No change',
}
