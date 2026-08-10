type EmptyScreenProps = {
  title: string
  scene?: string
  blurb: string
}

/** Placeholder for screens that land in weeks 3–4. No broken empty states. */
export function EmptyScreen({ title, scene, blurb }: EmptyScreenProps) {
  return (
    <div className="max-w-3xl">
      <p className="text-xs uppercase tracking-[0.14em] text-ink-faint mb-2">
        {scene || 'Demo screen'}
      </p>
      <h1 className="font-display text-4xl text-ink mb-3">{title}</h1>
      <p className="text-ink-muted text-base leading-relaxed mb-8">{blurb}</p>
      <div className="rounded-lg border border-line bg-surface-raised shadow-shell p-6">
        <p className="text-sm font-medium text-ink">Coming in a later sprint</p>
        <p className="text-sm text-ink-muted mt-2 leading-relaxed">
          This route is wired and navigable. Content ships with the intelligence
          layer — the shell stays empty on purpose.
        </p>
      </div>
    </div>
  )
}
