import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BarChartBig } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { WorkloadResult } from '@/types'

const usd = (v: unknown) => `$${Number(v).toFixed(2)}`

/** Potential saving (optimizer) vs counted saving (approved only). The gap is what the Critic held back. */
export default function SavingsChart({ results }: { results: WorkloadResult[] }) {
  const data = results.map((r) => ({
    name: r.workload_id,
    // Potential includes what a safety rule refused: the optimizer did find that money, so
    // leaving it out here would understate the opportunity and hide the cost of the rules.
    Potential: r.proposal.estimated_monthly_saving_usd + (r.proposal.suppressed_saving_usd ?? 0),
    Realised: r.monthly_savings_estimate_usd,
  }))
  const held = data.reduce((n, d) => n + (d.Potential - d.Realised), 0)
  const anySaving = data.some((d) => d.Potential > 0)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Savings: potential vs realised</CardTitle>
        <CardDescription>
          ${held.toFixed(2)} / mo held back by the Critic · illustrative
        </CardDescription>
      </CardHeader>
      <CardContent>
        {anySaving ? (
          <div className="h-44" role="img" aria-label={`Savings per workload: ${data.map((d) => `${d.name} potential ${usd(d.Potential)}, realised ${usd(d.Realised)}`).join('; ')}`}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }} barGap={2}>
                <CartesianGrid horizontal={false} stroke="var(--border)" />
                <XAxis type="number" tickFormatter={usd} tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" width={110} tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip formatter={usd} cursor={{ fill: 'var(--accent)' }} contentStyle={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} itemStyle={{ color: 'var(--foreground)' }} labelStyle={{ color: 'var(--foreground)' }} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="Potential" fill="var(--muted-foreground)" fillOpacity={0.45} radius={[0, 4, 4, 0]} />
                <Bar dataKey="Realised" fill="var(--primary)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="flex h-44 flex-col items-center justify-center gap-2 rounded-md border border-dashed text-sm text-muted-foreground">
            <BarChartBig className="size-6" aria-hidden />
            No saving was found in this run.
          </p>
        )}
      </CardContent>
    </Card>
  )
}