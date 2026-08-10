import { EmptyScreen } from './EmptyScreen'

export function HomePage() {
  return (
    <EmptyScreen
      title="Overview"
      scene="Shell"
      blurb="Landing overview for the eight demo scenes. Screen content arrives with later tickets."
    />
  )
}

export function ConnectionsPage() {
  return (
    <EmptyScreen
      title="Connections"
      scene="Scene 1"
      blurb="Source connections and sync status for the corpus."
    />
  )
}

export function CorpusPage() {
  return (
    <EmptyScreen
      title="Corpus dashboard"
      scene="Scene 1"
      blurb="Live corpus counts from /corpus/stats will land here — tickets, accounts, analysts, channels."
    />
  )
}

export function Ticket360Page() {
  return (
    <EmptyScreen
      title="Ticket 360"
      scene="Scene 2"
      blurb="Full ticket workspace with timeline and related entities."
    />
  )
}

export function ContextPage() {
  return (
    <EmptyScreen
      title="Context & citations"
      scene="Scene 3"
      blurb="Retrieved context and citation trail for an analyst decision."
    />
  )
}

export function ExplainersPage() {
  return (
    <EmptyScreen
      title="Explainers"
      scene="Scene 3"
      blurb="Why the system recommended an action — readable, not a raw chain dump."
    />
  )
}

export function RecommendationPage() {
  return (
    <EmptyScreen
      title="Analyst recommendation"
      scene="Scene 4"
      blurb="Recommended next action with confidence and guardrails."
    />
  )
}

export function CallPlayerPage() {
  return (
    <EmptyScreen
      title="Call player"
      scene="Scene 5"
      blurb="Playback and transcript for voice interactions tied to a ticket."
    />
  )
}

export function ApprovalsPage() {
  return (
    <EmptyScreen
      title="Approval queue"
      scene="Scene 6"
      blurb="Human-in-the-loop approvals for high-risk write-backs."
    />
  )
}

export function AuditPage() {
  return (
    <EmptyScreen
      title="Audit viewer"
      scene="Scene 7"
      blurb="Immutable trail of agent actions and approvals."
    />
  )
}

export function KbReviewPage() {
  return (
    <EmptyScreen
      title="KB review"
      scene="Scene 7"
      blurb="Knowledge-base article drafts awaiting review."
    />
  )
}

export function DigestPage() {
  return (
    <EmptyScreen
      title="Weekly digest"
      scene="Scene 8"
      blurb="Executive weekly narrative across the portfolio of tickets and outcomes."
    />
  )
}
