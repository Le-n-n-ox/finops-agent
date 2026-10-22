/**
 * The percentage change from one request to the next, rounded for display.
 * Returns an em dash when there is nothing to compare against.
 */
export const delta = (cur: number | null, next: number | null | undefined) =>
  cur && next != null ? `${Math.round(((next - cur) / cur) * 100)}%` : '—'
