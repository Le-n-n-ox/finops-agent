import type { ReactNode } from 'react'

/**
 * The label that names a group of panels on the analysis page.
 *
 * The page is long, and a reader who lands in the middle of it — from a search result, a shared
 * link, or a half-remembered scroll — needs to know which part of the run they are looking at.
 * The shape is the same as the landing page's eyebrow, so the two pages speak one language.
 */
export default function Band({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <h2 className="shrink-0 text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
        {title}
      </h2>
      <span aria-hidden className="h-px flex-1 bg-border" />
      {children}
    </div>
  )
}
