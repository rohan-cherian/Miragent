/* S-06 · Context & citations panel [F-083, F-052, F-054, F-051].
   Scope Class: POC functional.

   The moat, made visible: what the system knows, where each piece came from, and
   what it deliberately withheld. The pack header reports its own coverage and its
   own system count; if the count is below the target the header says so with the
   reason, rather than quietly rendering a thinner pack. */

import React, { useState } from 'react'
import { EvidenceCard } from '../../ui/data.jsx'
import { Button, Chip, Meter } from '../../ui/primitives.jsx'
import { LoadingWithBudget, Notice, SkeletonBlock, EmptyState } from '../../ui/feedback.jsx'
import { useAsync } from '../../shell/hooks.js'
import * as api from '../../mock/api.js'
import { config } from '../../contracts/config.js'
import { absolute, ms } from '../../contracts/format.js'
import { systemName } from '../../fixtures/corpus.js'
import { emit } from '../../contracts/telemetry.js'

export default function Citations({ caseId, focusCard, onFocusCard }) {
  const { data: pack, loading, error, reload } = useAsync(() => api.getContextPack(caseId), [caseId])
  const [reEnriching, setReEnriching] = useState(false)
  const [reEnriched, setReEnriched] = useState(false)

  if (loading) {
    return (
      <LoadingWithBudget budgetMs={config.budgets_ms.context_pack} label="Compiling the context pack">
        <SkeletonBlock lines={10} />
      </LoadingWithBudget>
    )
  }
  if (error || !pack) {
    return <Notice tone="danger" title="Context compiler unreachable">
      The pack could not be compiled. Nothing is fabricated in its place.
      <Button variant="secondary" size="sm" onClick={reload}>Retry</Button>
    </Notice>
  }

  const bySystem = pack.cards.reduce((acc, c) => {
    (acc[c.source_system] ||= []).push(c)
    return acc
  }, {})
  const thin = pack.systems_in_pack < config.min_systems_in_pack

  const requestReEnrich = async () => {
    setReEnriching(true)
    emit('citation_drilldown', { action: 're_enrich', case: caseId })
    setTimeout(() => { setReEnriching(false); setReEnriched(true) }, 1800)
  }

  return (
    <div className="stack gap-4">
      {/* ---- Pack header: the pack reports on itself ---- */}
      <div className="card">
        <div className="row gap-3 wrap">
          <div>
            <div className="caption">Compiled</div>
            <div className="strong" title={absolute(pack.compiled_at)}>{ms(pack.compile_ms)}</div>
            <div className="meta">budget {ms(config.budgets_ms.context_pack)}</div>
          </div>
          <div>
            <div className="caption">Systems in pack</div>
            <div className="row gap-2">
              <span className="strong num">{pack.systems_in_pack}</span>
              {thin
                ? <Chip tone="warning" icon="⚠">below target of {config.min_systems_in_pack}</Chip>
                : <Chip tone="success" icon="✓">≥{config.min_systems_in_pack}</Chip>}
            </div>
            <div className="meta">cross-system context is the whole differentiation</div>
          </div>
          <div>
            <div className="caption">Citation coverage</div>
            <div className="strong num">{Math.round(pack.citation_coverage * 100)}%</div>
            <Meter value={pack.citation_coverage}
                   tone={pack.citation_coverage >= 0.9 ? 'success' : 'warning'}
                   label="citation coverage" />
          </div>
          <div>
            <div className="caption">Token budget used</div>
            <div className="strong num">{Math.round(pack.token_budget_used * 100)}%</div>
          </div>
          <div className="right">
            {pack.filtered_count > 0 && (
              <Chip tone="neutral" icon="▨"
                    title="The trust filter removed items your context should not see. The count is shown; the content is not.">
                filtered: {pack.filtered_count}
              </Chip>
            )}
          </div>
        </div>

        {pack.over_budget && (
          <div style={{ marginTop: 'var(--sp-3)' }}>
            <Notice tone="warning" icon="⏳">
              Compilation ran past its {ms(config.budgets_ms.context_pack)} budget. The honest figure is shown
              rather than a rounded one — a slow pack is a fact, not something to hide behind a spinner.
            </Notice>
          </div>
        )}
      </div>

      {/* ---- Low context: cause + action, and fast-approve is suppressed ---- */}
      {pack.low_context && !reEnriched && (
        <Notice tone="warning" icon="⚠" title="Insufficient context"
                action={
                  <Button variant="secondary" size="sm" loading={reEnriching} onClick={requestReEnrich}>
                    Request re-enrichment
                  </Button>
                }>
          {pack.low_context_cause}{' '}
          The pipeline paused for enrichment rather than answering from too little. One-click approval is
          suppressed on this item, and any draft sentence that cannot be cited is withheld.
        </Notice>
      )}
      {reEnriched && (
        <Notice tone="info" icon="↻" title="Re-enrichment requested">
          The request is recorded in the audit trail. No external system was written to — asking for more
          context is a read, and it is still logged.
        </Notice>
      )}

      {/* ---- Evidence cards, grouped by source system ---- */}
      {!pack.cards.length && (
        <EmptyState icon="∅" title="No evidence retrieved"
                    message="Retrieval returned nothing above threshold. The case routes to human triage rather than being answered." />
      )}

      {Object.entries(bySystem).map(([sys, cards]) => (
        <section key={sys}>
          <div className="section-head">
            <h3 className="section-title" style={{ fontSize: 'var(--fs-body)' }}>{systemName(sys)}</h3>
            <span className="caption">{cards.length} item{cards.length > 1 ? 's' : ''}</span>
          </div>
          {cards.map((c) => (
            <EvidenceCard
              key={c.n}
              card={c}
              focused={focusCard === c.n}
              expandedByDefault={pack.low_context}
              onOpen={c.deep_link ? () => { emit('citation_drilldown', { card: c.n }); window.location.hash = c.deep_link } : undefined}
            />
          ))}
        </section>
      ))}

      {/* ---- Footer: what was withheld ---- */}
      <div className="card" style={{ background: 'var(--surface-1)' }}>
        <div className="row gap-3 wrap caption">
          <span>
            <strong>{pack.withheld_count}</strong> draft sentence{pack.withheld_count === 1 ? '' : 's'} withheld
            for lack of a supporting citation.
          </span>
          <span>
            <strong>{pack.filtered_count}</strong> item{pack.filtered_count === 1 ? '' : 's'} removed by the trust filter.
          </span>
        </div>
        <p className="meta" style={{ marginTop: 'var(--sp-2)', marginBottom: 0 }}>
          Both numbers are shown on purpose. A reviewer needs to know that filtering happened without
          seeing what was filtered, and needs to see what the system refused to claim.
        </p>
      </div>
    </div>
  )
}
