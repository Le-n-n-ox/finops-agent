import { useState } from 'react'
import { toast } from 'sonner'
import { Check, MessageSquareWarning, X } from 'lucide-react'
import { submitReview } from '@/api'
import { Button } from '@/components/ui/button'
import type { ReviewAction } from '@/types'

interface Props {
  reportId: string
  workloadId: string
  /** Approved decisions can be accepted; anything can be rejected or flagged. */
  canAccept: boolean
  onRecorded?: () => void
}

/**
 * Record a human review action.
 *
 * This is a workflow record only. Accepting a decision for implementation never deploys
 * anything - it marks the recommendation as reviewed. A rejection carries structured reasons,
 * which the agent replays as "Historical Lessons" the next time it analyses this workload.
 */
export default function ReviewForm({ reportId, workloadId, canAccept, onRecorded }: Props) {
  const [open, setOpen] = useState(false)
  const [action, setAction] = useState<ReviewAction>('REJECTED')
  const [comment, setComment] = useState('')
  const [reviewer, setReviewer] = useState('')
  const [reason, setReason] = useState('')
  const [resource, setResource] = useState('')
  const [guidance, setGuidance] = useState('')
  const [saving, setSaving] = useState(false)
  const [outcome, setOutcome] = useState('')

  const submit = async () => {
    setSaving(true)
    try {
      await submitReview(reportId, {
        workload_id: workloadId,
        action,
        comment: comment.trim() || null,
        reviewer: reviewer.trim() || null,
        rejection_reasons: reason.trim() ? [reason.trim()] : [],
        resource: resource.trim() || null,
        reviewer_guidance: guidance.trim() || null,
        outcome: outcome.trim() || null,
      })
      toast.success('Review recorded')
      setOpen(false)
      setComment(''); setReason(''); setGuidance(''); setResource(''); setOutcome('')
      onRecorded?.()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not record the review')
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <MessageSquareWarning aria-hidden />Record a review
      </Button>
    )
  }

  return (
    <section className="space-y-3 rounded-md border p-3" aria-label="Record a review decision">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Record a review</h3>
        <Button variant="ghost" size="icon" className="size-7" onClick={() => setOpen(false)} aria-label="Cancel review">
          <X />
        </Button>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {(['REJECTED', 'NEEDS_INVESTIGATION', 'ACCEPTED_FOR_IMPLEMENTATION'] as ReviewAction[]).map((value) => (
          <Button
            key={value}
            variant={action === value ? 'secondary' : 'ghost'}
            size="sm"
            className="h-7"
            disabled={value === 'ACCEPTED_FOR_IMPLEMENTATION' && !canAccept}
            aria-pressed={action === value}
            onClick={() => setAction(value)}
            title={value === 'ACCEPTED_FOR_IMPLEMENTATION' && !canAccept ? 'Only approved decisions can be accepted' : undefined}
          >
            {value === 'ACCEPTED_FOR_IMPLEMENTATION' ? 'Accept' : value === 'REJECTED' ? 'Reject' : 'Investigate'}
          </Button>
        ))}
      </div>

      <label className="block space-y-1 text-xs">
        <span className="font-medium">Reviewer</span>
        <input
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
          placeholder="Your name"
          className="h-8 w-full rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        />
      </label>

      {action === 'REJECTED' && (
        <>
          <label className="block space-y-1 text-xs">
            <span className="font-medium">Why was it rejected?</span>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. memory reduction caused an OOMKill"
              className="h-8 w-full rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />
          </label>
          <label className="block space-y-1 text-xs">
            <span className="font-medium">Which resource?</span>
            <input
              value={resource}
              onChange={(e) => setResource(e.target.value)}
              placeholder="cpu or memory"
              className="h-8 w-full rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />
          </label>
          <label className="block space-y-1 text-xs">
            <span className="font-medium">Guidance for next time</span>
            <input
              value={guidance}
              onChange={(e) => setGuidance(e.target.value)}
              placeholder="e.g. keep memory, cpu is fine"
              className="h-8 w-full rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />
          </label>
          <p className="text-xs text-muted-foreground">
            A rejection is replayed to the agent as a lesson on the next analysis of this workload.
          </p>
        </>
      )}

      <label className="block space-y-1 text-xs">
        <span className="font-medium">Comment</span>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={2}
          className="w-full rounded-md border bg-background px-2 py-1 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        />
      </label>

      {action === 'ACCEPTED_FOR_IMPLEMENTATION' && (
        <label className="block space-y-1 text-xs">
          <span className="font-medium">Outcome (optional)</span>
          <input
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            placeholder="e.g. applied to one replica, no throttling after 30 min"
            className="h-8 w-full rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          <span className="block text-muted-foreground">
            Recorded against the decision so a later reviewer can see whether the change actually worked.
          </span>
        </label>
      )}

      <Button size="sm" onClick={() => void submit()} disabled={saving}>
        <Check aria-hidden />{saving ? 'Recording…' : 'Record review'}
      </Button>
      <p className="text-xs text-muted-foreground">
        Accepting marks the recommendation as reviewed. Nothing is applied to a cluster.
      </p>
    </section>
  )
}
