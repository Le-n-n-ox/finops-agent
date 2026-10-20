import { cn } from '@/lib/utils'

/** Renders a unified-diff-style patch with +/- line colouring (also marked with the +/- glyph, not colour alone). */
export default function YamlDiff({ patch }: { patch: string }) {
  return (
    <pre className="max-h-72 overflow-auto rounded-md border bg-muted py-2 font-mono text-xs">
      {patch.split('\n').map((line, i) => (
        <div
          key={i}
          className={cn(
            'px-3 whitespace-pre',
            line.startsWith('+') && !line.startsWith('+++') && 'bg-emerald-500/15 text-emerald-800 dark:text-emerald-300',
            line.startsWith('-') && !line.startsWith('---') && 'bg-red-500/15 text-red-800 dark:text-red-300',
            (line.startsWith('@@') || line.startsWith('#')) && 'text-muted-foreground',
          )}
        >
          {line || ' '}
        </div>
      ))}
    </pre>
  )
}