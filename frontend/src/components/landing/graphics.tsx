import type { CSSProperties } from 'react'
import { cn } from '@/lib/utils'
import { DECISION_COLOR, DECISION_ORDER, type DecisionCounts, type DecisionKey } from './decisions'

/**
 * The graphics on the landing page.
 *
 * They are hand-drawn SVG rather than chart-library output for two reasons: the page has to
 * animate (lines that draw themselves, segments that arrive in sequence) and the charts here
 * are illustrations of the method, not data read off a live endpoint.
 */

/* ------------------------------------------------------------------ usage sparkline */

/** An illustrative CPU series against a flat request. Its peak is the P99 the critic floors at. */
const HOURLY_USAGE = [
  138, 142, 135, 150, 147, 160, 152, 158, 165, 171, 160, 158, 150, 144, 152, 168, 175, 182, 190, 205,
  198, 188, 176, 168, 160, 155, 150, 146, 152, 158, 164, 172, 180, 188, 196, 204, 210, 208, 205, 210,
]

export function UsageSparkline({ className }: { className?: string }) {
  const w = 320
  const h = 100
  const pad = 8
  // A little headroom above the request line, so its label has somewhere to sit.
  const top = 20
  const request = 800
  const step = (w - pad * 2) / (HOURLY_USAGE.length - 1)
  const y = (v: number) => h - pad - (v / request) * (h - pad - top)
  const points = HOURLY_USAGE.map((v, i) => [pad + i * step, y(v)])
  const line = points
    .map(([x, py], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${py.toFixed(1)}`)
    .join(' ')
  const area = `${line} L ${points[points.length - 1][0].toFixed(1)} ${h - pad} L ${pad} ${h - pad} Z`
  const reserved = `${line} L ${points[points.length - 1][0].toFixed(1)} ${y(request)} L ${pad} ${y(request)} Z`
  const last = points[points.length - 1]

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className={cn('h-auto w-full', className)}
      role="img"
      aria-label="Illustrative hourly CPU usage of one workload: the series peaks at 210 millicores while the request stays at 800."
    >
      <defs>
        <linearGradient id="lp-spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--lp-teal)" stopOpacity="0.26" />
          <stop offset="100%" stopColor="var(--lp-teal)" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {/* The band between the usage and the request: the capacity that is reserved and idle. */}
      <path d={reserved} fill="var(--lp-amber)" fillOpacity="0.1" className="lp-fade" />
      {/* The request: a reference line, not a series. Labelled where it is drawn. */}
      <line x1={pad} y1={y(request)} x2={w - pad} y2={y(request)} stroke="var(--lp-axis)" strokeWidth="1" strokeDasharray="5 5" />
      <text x={pad + 2} y={y(request) - 7} fontSize="10" fill="var(--muted-foreground)">
        request 800 m
      </text>
      <path d={area} fill="url(#lp-spark-fill)" className="lp-fade" />
      <path
        d={line}
        fill="none"
        stroke="var(--lp-teal)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        pathLength={1}
        className="lp-draw"
      />
      <circle cx={last[0]} cy={last[1]} r="3.5" fill="var(--lp-teal)" className="lp-bob" />
    </svg>
  )
}

/* ---------------------------------------------------------------- the unused request */

/** Thirty days of illustrative usage for one workload whose request is far above it. */
const DAILY_USAGE = [
  132, 128, 141, 136, 129, 144, 152, 148, 139, 133, 126, 131, 138, 145, 151, 158, 164, 159, 148, 141, 135,
  129, 134, 142, 150, 161, 172, 168, 196, 210,
]

/**
 * The gap between what a workload uses and what its request reserves.
 *
 * One series (the usage) against one reference line (the request), with the difference
 * between them drawn as a labelled region. There is no second series, so there is no legend
 * to read: the title says what the area is and the region says what the gap costs.
 */
export function WasteGapChart({ className }: { className?: string }) {
  const w = 640
  const h = 280
  const left = 46
  const right = 16
  const top = 22
  const bottom = 40
  const plotW = w - left - right
  const plotH = h - top - bottom
  const max = 900
  const request = 800
  const y = (v: number) => top + (1 - v / max) * plotH
  const step = plotW / (DAILY_USAGE.length - 1)
  const points = DAILY_USAGE.map((v, i) => [left + i * step, y(v)])
  const line = points.map(([px, py], i) => `${i ? 'L' : 'M'}${px.toFixed(1)} ${py.toFixed(1)}`).join(' ')
  const gapArea = `${line} L ${points[points.length - 1][0].toFixed(1)} ${y(request)} L ${left} ${y(request)} Z`
  const peak = points[DAILY_USAGE.length - 1]

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className={cn('h-auto w-full', className)}
      role="img"
      aria-label="Thirty days of usage for one workload. The request stays at 800 millicores while usage peaks at 210, so roughly 590 millicores are reserved and never used."
    >
      <defs>
        <linearGradient id="lp-gap-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--lp-amber)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--lp-amber)" stopOpacity="0.06" />
        </linearGradient>
        <pattern id="lp-hatch" width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0" x2="0" y2="7" stroke="var(--lp-amber)" strokeWidth="1.5" strokeOpacity="0.4" />
        </pattern>
      </defs>

      {/* Gridlines: hairlines, recessive. */}
      {[0, 300, 600, 900].map((v) => (
        <g key={v}>
          <line x1={left} y1={y(v)} x2={w - right} y2={y(v)} stroke="var(--lp-grid)" strokeWidth="1" />
          <text x={left - 10} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--muted-foreground)">
            {v === 0 ? '0' : v === 900 ? '900 m' : v}
          </text>
        </g>
      ))}

      <path d={gapArea} fill="url(#lp-gap-fill)" className="lp-fade" />
      <path d={gapArea} fill="url(#lp-hatch)" className="lp-fade" />

      <path
        d={line}
        fill="none"
        stroke="var(--lp-teal)"
        strokeWidth="2.25"
        strokeLinecap="round"
        strokeLinejoin="round"
        pathLength={1}
        className="lp-draw"
      />

      {/* The request, and the peak it never reaches. */}
      <line x1={left} y1={y(request)} x2={w - right} y2={y(request)} stroke="var(--lp-axis)" strokeWidth="1.5" strokeDasharray="6 5" />
      <text x={w - right} y={y(request) - 9} textAnchor="end" fontSize="12" fontWeight="500" fill="var(--foreground)">
        request 800 m
      </text>

      {/* The peak is called out on a leader line, below the series, so the label never
          lands on the line it is describing. */}
      <circle cx={peak[0]} cy={peak[1]} r="4" fill="var(--lp-teal)" />
      <path
        d={`M${peak[0].toFixed(1)} ${(peak[1] + 7).toFixed(1)} V${(peak[1] + 19).toFixed(1)}`}
        stroke="var(--lp-axis)"
        strokeWidth="1"
        fill="none"
      />
      <text x={peak[0] - 2} y={peak[1] + 32} textAnchor="end" fontSize="12" fontWeight="500" fill="var(--foreground)">
        p99 210 m
      </text>

      <text x={left + plotW / 2} y={y(request) + 34} textAnchor="middle" fontSize="12" fill="var(--muted-foreground)">
        ~590 m reserved every hour and never used
      </text>

      {['day 1', 'day 8', 'day 15', 'day 22', 'day 29'].map((label, i) => (
        <text
          key={label}
          x={left + (plotW / 4) * i}
          y={h - 14}
          textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}
          fontSize="11"
          fill="var(--muted-foreground)"
        >
          {label}
        </text>
      ))}
    </svg>
  )
}

/* ------------------------------------------------------------------ decision ring */

export function DecisionRing({
  counts,
  className,
}: {
  counts: DecisionCounts
  className?: string
}) {
  const size = 190
  const r = 76
  const stroke = 21
  const circumference = 2 * Math.PI * r
  const present = DECISION_ORDER.filter((k) => counts[k] > 0)
  const sum = present.reduce((n, k) => n + counts[k], 0)
  // A 3-unit gap between segments, in circumference units: the surface shows through it, so
  // two neighbouring segments never read as one block.
  const gap = sum > 1 ? 3 : 0
  const lengthOf = (k: DecisionKey) => (counts[k] / sum) * circumference
  const startOf = (index: number) =>
    present.slice(0, index).reduce((n, key) => n + lengthOf(key), 0)

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      className={cn('h-auto w-full', className)}
      role="img"
      aria-label={`Decisions in the last run: ${present
        .map((k) => `${counts[k]} ${k.replace('_', ' ')}`)
        .join(', ')}.`}
    >
      <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
        {present.map((k, i) => {
          const dash = Math.max(0, lengthOf(k) - gap)
          return (
            <circle
              key={k}
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke={DECISION_COLOR[k]}
              strokeWidth={stroke}
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-(startOf(i) + gap / 2)}
              className="lp-fade"
              style={{ animationDelay: `${i * 110}ms` } as CSSProperties}
            />
          )
        })}
      </g>
    </svg>
  )
}

/* ------------------------------------------------------------------ confidence bar */

/**
 * The verification score, as a stacked bar.
 *
 * Two series, so the pair was validated as a set against both surfaces: the teal and the
 * violet are far apart under every kind of colour vision, and both are legible on the light
 * and the dark surface.
 */
export function ConfidenceBar({ className }: { className?: string }) {
  return (
    <div className={className}>
      <div className="flex h-3.5 w-full gap-[2px] overflow-hidden rounded-full">
        <div className="h-full rounded-l-full" style={{ width: '60%', background: 'var(--lp-teal)' }} />
        <div className="h-full rounded-r-full" style={{ width: '40%', background: 'var(--lp-violet)' }} />
      </div>
      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <span className="flex items-center gap-2">
          <span className="size-2.5 rounded-full" style={{ background: 'var(--lp-teal)' }} aria-hidden />
          <span className="text-muted-foreground">Traceability</span>
          <span className="font-medium tabular-nums">0.60</span>
        </span>
        <span className="flex items-center gap-2">
          <span className="size-2.5 rounded-full" style={{ background: 'var(--lp-violet)' }} aria-hidden />
          <span className="text-muted-foreground">Evidence</span>
          <span className="font-medium tabular-nums">0.40</span>
        </span>
        <span className="text-muted-foreground">
          minus overlap and objection penalties
        </span>
      </div>
    </div>
  )
}
