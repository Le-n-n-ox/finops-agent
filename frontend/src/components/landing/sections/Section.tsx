import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * The frame every section sits in: a small eyebrow, a headline, a lede, then the content.
 * One frame means the page reads as one document rather than a stack of unrelated blocks.
 */
export function Section({
  id,
  eyebrow,
  title,
  lede,
  children,
  className,
  tone = 'plain',
}: {
  id?: string
  eyebrow: string
  title: ReactNode
  lede?: ReactNode
  children: ReactNode
  className?: string
  tone?: 'plain' | 'tinted'
}) {
  return (
    <section
      id={id}
      className={cn(
        'scroll-mt-24 border-t border-border/70 py-20 lg:py-28',
        tone === 'tinted' && 'bg-muted/25',
        className,
      )}
    >
      <div className="mx-auto w-full max-w-[1200px] px-4 lg:px-6">
        <div className="max-w-3xl">
          <p className="flex items-center gap-2 text-xs font-semibold tracking-[0.14em] text-primary uppercase">
            <span className="h-px w-6 bg-primary/60" aria-hidden />
            {eyebrow}
          </p>
          <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
            {title}
          </h2>
          {lede && <p className="mt-4 text-pretty text-base leading-relaxed text-muted-foreground sm:text-lg">{lede}</p>}
        </div>
        <div className="mt-12">{children}</div>
      </div>
    </section>
  )
}
