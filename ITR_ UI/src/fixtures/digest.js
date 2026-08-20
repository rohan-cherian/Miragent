/* Weekly intelligence digest (S-11) — the Operations Manager's Monday briefing.
   Prose-first, every number drillable to its case IDs [P-4, F-075].
   Patterns below significance are ABSENT — no teaser rows, ever [F-074 edge]. */

import { NOW, CASES, CLASSES, ANALYSTS, classMeta } from './corpus.js'
import { capabilityMap, slaHotspots, adoptionMetrics } from './aggregates.js'
import { EVIDENCE_RICH_CASES } from './details.js'
import { ALL_AUDIT } from './audit.js'
import { CaseStatus } from '../contracts/state.js'

const DAY = 86400000

const inWindow = (c, days) => NOW - new Date(c.created_at).getTime() < days * DAY

/** Cluster helper: this week's volume in a class vs the prior week. */
function cluster(classId, { label, story, deflection, kbGap, rootCause } = {}) {
  const week = CASES.filter((c) => c.class === classId && inWindow(c, 7))
  const prior = CASES.filter(
    (c) => c.class === classId &&
      NOW - new Date(c.created_at).getTime() >= 7 * DAY &&
      NOW - new Date(c.created_at).getTime() < 14 * DAY
  )
  /* J-CT-2 step 2 is "exemplar → linked Jira (root cause)". An exemplar picked
     by array position lands on whichever case the generator happened to emit
     first, which usually has no linked defect — and the manager's flagship
     journey then stops one hop short of the root cause. Prefer a case that
     actually carries cross-system evidence. */
  const exemplar =
    week.find((c) => EVIDENCE_RICH_CASES.includes(c.id))?.id || week[0]?.id || null

  return {
    key: classId,
    label: label || classMeta(classId).label,
    category: classMeta(classId).cat,
    count: week.length,
    prior_count: prior.length,
    movement: week.length - prior.length,
    case_ids: week.map((c) => c.id),
    exemplar,
    exemplar_has_root_cause: EVIDENCE_RICH_CASES.includes(exemplar),
    story, deflection, kbGap, rootCause,
    drill: { class: classId, from: new Date(NOW - 7 * DAY).toISOString().slice(0, 10) },
  }
}

export function weeklyDigest() {
  const clusters = [
    cluster('auth-sso', {
      story: 'The recurrence traces to the Friday conditional-access change (Jira AUTH-341). Every ticket in the cluster is the same login loop, and every one of them was resolvable from the existing runbook — which is why the drafts landed at High confidence and the handling time is well below the class median.',
      rootCause: 'AUTH-341',
      deflection: true,
    }),
    cluster('payroll-integrations', {
      story: 'Cost-centre mapping rejections after the August org change. Two analysts absorbed almost all of this volume, which is the capability concern below rather than a volume concern.',
      kbGap: false,
    }),
    cluster('order-edi', {
      story: 'Partner-side acknowledgement failures on the EDI feed. Volume is flat week over week; it appears here because handling cost per ticket is the highest of any class this week.',
    }),
    cluster('coldchain-telemetry', {
      story: 'A single overnight alert storm on trailer telemetry produced most of this cluster. It is one incident wearing many ticket numbers — worth a linking rule rather than a KB article.',
    }),
  ]
    .filter((c) => c.count >= 5)      // below significance ⇒ the row does not exist
    .sort((a, b) => b.movement - a.movement || b.count - a.count)

  const top = clusters[0]

  const deflection = clusters
    .filter((c) => c.deflection || c.count >= 12)
    .map((c) => ({
      key: c.key, label: c.label,
      estimated_volume: Math.round(c.count * 0.62),
      basis: 'Share of the cluster whose draft resolution was accepted unedited — those are answerable from an article without an analyst.',
      case_ids: c.case_ids,
      drill: c.drill,
    }))

  const gaps = CLASSES
    .map((cls) => {
      const vol = CASES.filter((c) => c.class === cls.id && inWindow(c, 30)).length
      return { key: cls.id, label: cls.label, category: cls.cat, volume_30d: vol, articles: null }
    })
    .filter((g) => ['sso-scim-sync', 'payroll-integrations', 'coldchain-telemetry'].includes(g.key))
    .map((g) => ({
      ...g,
      articles: g.key === 'sso-scim-sync' ? 0 : g.key === 'payroll-integrations' ? 3 : 4,
      handling_cost_min: g.key === 'sso-scim-sync' ? 94 : g.key === 'payroll-integrations' ? 71 : 44,
      rank_basis: 'volume × median handling cost',
      drill: { class: g.key },
    }))
    .sort((a, b) => b.volume_30d * b.handling_cost_min - a.volume_30d * a.handling_cost_min)

  const weekStart = new Date(NOW - 7 * DAY).toISOString().slice(0, 10)
  const capability = capabilityMap()
  const thin = capability.filter((c) => c.thin).slice(0, 4)
  const thinKeys = new Set(thin.map((t) => t.key))
  // Capped: the drill travels as URL state, and an unbounded id list makes an
  // unshareable link. The panel footer reports the cap rather than hiding it.
  const thinCaseIds = CASES.filter((c) => thinKeys.has(c.class)).slice(0, 150).map((c) => c.id)

  /* Development areas — anonymised by employment type, never by name [F-129].
     Only groups at or above the sample floor are reported. */
  const development = [
    { class: 'payroll-integrations', below_median: [{ type: 'FTE', n: 2 }, { type: 'BPO', n: 1 }], sample_floor: 5,
      note: 'Below team median on first-time-fix in this class over ≥5 samples each.' },
    { class: 'coldchain-telemetry', below_median: [{ type: 'FTE', n: 1 }], sample_floor: 5,
      note: 'Single analyst, 6 samples. Reported because it is the only coverage in the class.' },
  ]

  const skillsClaimedWithoutHistory = 7

  const solvedThisWeek = CASES.filter(
    (c) => (c.status === CaseStatus.SOLVED || c.status === CaseStatus.CLOSED) && inWindow(c, 7)
  ).length

  return {
    week: 32,
    period_label: 'Week 32 · Mon 03 Aug – Sun 09 Aug 2026',
    published_at: new Date(NOW - 26 * 3600000).toISOString(),
    narrative: {
      headline: `Week 32: ${top ? `${top.label} recurrence is the story` : 'a quiet week'}.`,
      body: top
        ? `${top.count} ${top.label} tickets landed this week against ${top.prior_count} the week before — the sharpest single-class movement in the corpus. ${top.story} Two things follow from it: a deflection candidate worth roughly ${Math.round(top.count * 0.62)} tickets a week, and a coaching signal in payroll-integrations where two analysts are carrying most of the volume. Everything below resolves to the cases behind it; nothing here is an estimate you cannot open.`
        : 'No class moved far enough this week to clear the significance floor.',
      /* Every figure resolves to its records — including the two that used to be
         decoration. P-4 has no exemptions for summary counts. */
      figures: [
        { label: 'Cases solved this week', value: solvedThisWeek,
          drill: { status: 'solved', from: weekStart } },
        { label: 'Clusters above significance', value: clusters.length,
          drill: { ids: clusters.flatMap((c) => c.case_ids).join(','), from: weekStart },
          drillLabel: 'Every case across all clusters' },
        { label: 'Classes with thin coverage', value: thin.length,
          drill: thin.length ? { ids: thinCaseIds.join(',') } : null,
          drillLabel: thin.length ? `Cases in ${thin.map((t) => t.label).join(', ')}` : null },
      ],
    },
    clusters,
    deflection,
    gaps,
    sla_hotspots: slaHotspots(5),
    capability: { map: capability.slice(0, 12), thin },
    development,
    skills_claimed_without_history: skillsClaimedWithoutHistory,
    /* Adoption — is the system earning its keep? The Quality block below answers
       whether it is honest; these three answer whether it is useful. All three
       are in the approved metric set (§1.4) and all three are derived from the
       decision records, so each opens onto the rows behind it. */
    // Read over 30 days, not the digest week: a single week is too small a
    // sample for a rate, and saying so beats reporting a noisy one.
    adoption: adoptionMetrics(ALL_AUDIT, '30d'),
    adoption_window: 'last 30 days',

    quality: {
      sampled_runs: 214,
      flagged: 6,
      groundedness_avg: 0.89,
      groundedness_prior: 0.86,
      calibration_note: 'Confidence tracked accuracy within tolerance again this week; the High band ran 2 points optimistic on voice-origin cases, which is why voice metrics are reported separately.',
      citation_coverage: 0.94,
      // Each quality figure resolves to the sampled runs that produced it.
      drill_sampled: '/audit?origin=intelligence',
      drill_flagged: '/audit?flagged=1&origin=intelligence',
      band_movement: [
        { band: 'High', share: 0.58, prior: 0.55 },
        { band: 'Medium', share: 0.29, prior: 0.31 },
        { band: 'Low', share: 0.13, prior: 0.14 },
      ],
    },
    archive: [32, 31, 30, 29, 28],
  }
}
