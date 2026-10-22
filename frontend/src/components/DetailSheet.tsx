import { useEffect, useRef } from 'react'
import type { WorkloadResult } from '@/types'
import DetailPanel from './DetailPanel'

/**
 * The detail panel as a bottom sheet on small screens.
 *
 * On a phone the panel covers most of the screen, so it has to behave like a dialog: the page
 * behind it must not scroll, Escape must close it, focus must move into it and come back to the
 * row that opened it afterwards.
 */
export default function DetailSheet({
  result,
  reportId,
  onClose,
  simulatorUnavailable,
}: {
  result: WorkloadResult
  reportId?: string
  onClose: () => void
  simulatorUnavailable?: string
}) {
  const sheetRef = useRef<HTMLDivElement>(null)
  const opener = useRef<HTMLElement | null>(null)

  useEffect(() => {
    opener.current = document.activeElement as HTMLElement | null
    const { body } = document
    const previousOverflow = body.style.overflow
    body.style.overflow = 'hidden'
    sheetRef.current?.focus()
    return () => {
      body.style.overflow = previousOverflow
      opener.current?.focus?.()
    }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      // A modal dialog keeps focus inside itself. Without this, tabbing walks off the bottom of
      // the sheet into the page underneath, which is still visible behind the backdrop.
      const focusables = sheetRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      if (!focusables?.length) return
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || !sheetRef.current?.contains(active))) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && active === last) {
        e.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div className="absolute inset-0 bg-black/50 animate-in fade-in motion-reduce:animate-none" onClick={onClose} aria-hidden />
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={`${result.workload_id} details`}
        tabIndex={-1}
        className="absolute inset-x-0 bottom-0 max-h-[90dvh] overflow-y-auto rounded-t-2xl bg-card shadow-2xl outline-none animate-in slide-in-from-bottom duration-300 motion-reduce:animate-none print:hidden"
      >
        <div className="sticky top-0 z-10 flex justify-center bg-card pt-2 pb-1" aria-hidden>
          <span className="h-1 w-10 rounded-full bg-border" />
        </div>
        <DetailPanel
          key={result.workload_id}
          result={result}
          reportId={reportId}
          onClose={onClose}
          simulatorUnavailable={simulatorUnavailable}
          className="rounded-b-none rounded-t-2xl border-b-0 animate-none pb-[env(safe-area-inset-bottom)]"
        />
      </div>
    </div>
  )
}
