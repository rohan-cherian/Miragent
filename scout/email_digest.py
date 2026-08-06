"""
scout/email_digest.py — Monday morning portfolio health email digest (Sprint 81).

Builds an HTML email summarising the latest InsightSnapshot per tenant and
sends it via SMTP (stdlib only — no third-party libraries).

Public API:
  build_digest_html(snapshots, generated_at) -> str
  send_digest(to_emails, html, subject)       -> bool
  build_and_send_portfolio_digest(db)         -> dict
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── HTML builder ──────────────────────────────────────────────────────────────

def _health_score(critical: int, high: int) -> int:
    """Simple formula: 100 - (critical*10 + high*5), floored at 0."""
    return max(0, 100 - (critical * 10 + high * 5))


def _severity_badge(label: str, count: int, bg: str, fg: str = "#FFFFFF") -> str:
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-size:11px;font-weight:700;padding:2px 8px;border-radius:12px;'
        f'margin-right:4px;">{label}: {count}</span>'
    )


def _company_card(snap: dict) -> str:
    """Render one company card as inline-CSS HTML."""
    tenant_id = snap.get("tenant_id", "unknown")
    profile = snap.get("company_profile") or {}
    company_name = profile.get("name") or tenant_id

    critical = snap.get("critical", 0)
    high = snap.get("high", 0)
    medium = snap.get("medium", 0)
    low = snap.get("low", 0)
    score = _health_score(critical, high)

    # Narrative snippet — truncate to 200 chars
    narrative = snap.get("narrative_snippet") or ""
    if len(narrative) > 200:
        narrative = narrative[:197] + "..."

    # Top findings (up to 3)
    top_findings: list = snap.get("top_findings") or []
    findings_html = ""
    for finding in top_findings[:3]:
        title = finding.get("title", str(finding)) if isinstance(finding, dict) else str(finding)
        sev = finding.get("severity", "") if isinstance(finding, dict) else ""
        sev_color = {"CRITICAL": "#C0392B", "HIGH": "#E67E22", "MEDIUM": "#F1C40F"}.get(sev, "#7F8C8D")
        findings_html += (
            f'<li style="margin-bottom:4px;">'
            f'<span style="color:{sev_color};font-weight:700;font-size:11px;">[{sev}]</span> '
            f'{title}</li>'
        ) if sev else f'<li style="margin-bottom:4px;">{title}</li>'

    findings_block = (
        f'<ul style="margin:8px 0 0 0;padding-left:18px;color:#444;font-size:13px;">'
        f'{findings_html}</ul>'
    ) if findings_html else '<p style="color:#888;font-size:13px;margin:6px 0 0 0;">No findings recorded.</p>'

    score_color = "#27AE60" if score >= 70 else ("#E67E22" if score >= 40 else "#C0392B")

    return f"""
<div style="background:#FFFFFF;border:1px solid #DEE3EC;border-radius:8px;
            padding:16px 20px;margin-bottom:16px;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td>
        <div style="font-size:16px;font-weight:700;color:#1B2A4A;margin-bottom:6px;">{company_name}</div>
        <div>
          {_severity_badge("Critical", critical, "#C0392B")}
          {_severity_badge("High", high, "#E67E22")}
          {_severity_badge("Medium", medium, "#F39C12")}
          {_severity_badge("Low", low, "#27AE60")}
        </div>
      </td>
      <td align="right" valign="top">
        <div style="font-size:28px;font-weight:800;color:{score_color};">{score}</div>
        <div style="font-size:10px;color:#888;text-align:center;">health score</div>
      </td>
    </tr>
  </table>
  {findings_block}
  {f'<p style="font-size:12px;color:#555;margin:10px 0 0 0;border-top:1px solid #EEF0F4;padding-top:8px;">{narrative}</p>' if narrative else ""}
</div>
"""


def build_digest_html(snapshots: list[dict], generated_at: datetime) -> str:
    """
    Build the full portfolio digest HTML email from a list of snapshot dicts.

    Each snapshot dict should have the same keys as InsightSnapshot columns.
    Returns a complete HTML document with inline CSS only.
    """
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    date_str = generated_at.strftime("%a %d %b %Y %H:%M UTC")

    total_companies = len(snapshots)
    companies_with_critical = sum(1 for s in snapshots if s.get("critical", 0) > 0)
    total_findings = sum(s.get("total_findings", 0) for s in snapshots)
    avg_score = (
        int(sum(_health_score(s.get("critical", 0), s.get("high", 0)) for s in snapshots) / total_companies)
        if total_companies > 0
        else 0
    )

    # Summary stats row
    stat_cell_style = (
        "text-align:center;padding:12px 20px;border-right:1px solid #DEE3EC;"
    )
    last_stat_style = "text-align:center;padding:12px 20px;"
    stats_html = f"""
<table width="100%" cellpadding="0" cellspacing="0"
       style="background:#FFFFFF;border:1px solid #DEE3EC;border-radius:8px;
              margin-bottom:24px;overflow:hidden;">
  <tr>
    <td style="{stat_cell_style}">
      <div style="font-size:28px;font-weight:800;color:#1B2A4A;">{total_companies}</div>
      <div style="font-size:11px;color:#888;">Companies</div>
    </td>
    <td style="{stat_cell_style}">
      <div style="font-size:28px;font-weight:800;color:#C0392B;">{companies_with_critical}</div>
      <div style="font-size:11px;color:#888;">With Critical</div>
    </td>
    <td style="{stat_cell_style}">
      <div style="font-size:28px;font-weight:800;color:#E67E22;">{total_findings}</div>
      <div style="font-size:11px;color:#888;">Total Findings</div>
    </td>
    <td style="{last_stat_style}">
      <div style="font-size:28px;font-weight:800;color:#27AE60;">{avg_score}</div>
      <div style="font-size:11px;color:#888;">Avg Health Score</div>
    </td>
  </tr>
</table>
"""

    # Company cards (sorted: critical first, then by health score ascending)
    sorted_snaps = sorted(
        snapshots,
        key=lambda s: (-s.get("critical", 0), -s.get("high", 0)),
    )
    cards_html = "".join(_company_card(s) for s in sorted_snaps)

    if not cards_html:
        cards_html = (
            '<p style="color:#888;text-align:center;padding:32px 0;">'
            'No portfolio data available for this digest.</p>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F4F6F9;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">

<!-- Wrapper -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F6F9;padding:32px 0;">
  <tr><td align="center">
    <table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">

      <!-- Header -->
      <tr>
        <td style="background:#1B2A4A;border-radius:8px 8px 0 0;padding:28px 32px;">
          <div style="font-size:22px;font-weight:800;color:#FFFFFF;letter-spacing:-0.5px;">
            Miragent
          </div>
          <div style="font-size:14px;color:#A8BBD4;margin-top:4px;">
            Portfolio Health Digest
          </div>
          <div style="font-size:12px;color:#6D8BAE;margin-top:8px;">{date_str}</div>
        </td>
      </tr>

      <!-- Body -->
      <tr>
        <td style="background:#F4F6F9;padding:24px 32px;">

          <h2 style="font-size:14px;font-weight:700;color:#1B2A4A;
                     text-transform:uppercase;letter-spacing:0.5px;margin:0 0 16px 0;">
            Portfolio Summary
          </h2>
          {stats_html}

          <h2 style="font-size:14px;font-weight:700;color:#1B2A4A;
                     text-transform:uppercase;letter-spacing:0.5px;margin:0 0 16px 0;">
            Company Breakdown
          </h2>
          {cards_html}

        </td>
      </tr>

      <!-- Footer -->
      <tr>
        <td style="background:#FFFFFF;border-top:1px solid #DEE3EC;border-radius:0 0 8px 8px;
                   padding:16px 32px;text-align:center;">
          <p style="font-size:11px;color:#AAB4C0;margin:0;">
            This digest is auto-generated by Miragent.
            To unsubscribe, contact your administrator.
          </p>
        </td>
      </tr>

    </table>
  </td></tr>
</table>

</body>
</html>"""
    return html


# ── SMTP sender ───────────────────────────────────────────────────────────────

def send_digest(to_emails: list[str], html: str, subject: str) -> bool:
    """
    Send the HTML digest via SMTP (stdlib only).

    Returns True on success, False if smtp_user is not configured or on error.
    Never raises — all exceptions are caught and logged.
    """
    from scout.config import settings

    if not settings.smtp_user:
        logger.warning(
            "email_digest: smtp_user is not configured — skipping send. "
            "Set SMTP_USER in your environment to enable email delivery."
        )
        return False

    if not to_emails:
        logger.warning("email_digest: no recipients — skipping send.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = ", ".join(to_emails)

        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.sendmail(settings.smtp_from, to_emails, msg.as_string())

        logger.info(
            "email_digest: digest sent to %d recipient(s): %s",
            len(to_emails),
            ", ".join(to_emails),
        )
        return True

    except Exception as exc:
        logger.error("email_digest: failed to send digest: %s", exc)
        return False


# ── Orchestrator ──────────────────────────────────────────────────────────────

def build_and_send_portfolio_digest(db: Session) -> dict:
    """
    Full orchestration:
      1. Query active portfolio-wide DigestRecipient rows (tenant_id IS NULL).
      2. Query the latest InsightSnapshot per tenant.
      3. Build HTML, send, return summary dict.

    Returns:
      {"sent": bool, "recipient_count": int, "company_count": int, "error": str|None}
    """
    from scout.db.models import DigestRecipient, InsightSnapshot

    error: Optional[str] = None

    try:
        # 1. Recipients
        recipients = (
            db.query(DigestRecipient)
            .filter(DigestRecipient.active.is_(True), DigestRecipient.tenant_id.is_(None))
            .all()
        )
        to_emails = [r.email for r in recipients]

        # 2. Latest snapshot per tenant
        subq = (
            db.query(
                InsightSnapshot.tenant_id,
                func.max(InsightSnapshot.run_at).label("max_run_at"),
            )
            .group_by(InsightSnapshot.tenant_id)
            .subquery()
        )
        latest_snapshots = (
            db.query(InsightSnapshot)
            .join(
                subq,
                (InsightSnapshot.tenant_id == subq.c.tenant_id)
                & (InsightSnapshot.run_at == subq.c.max_run_at),
            )
            .all()
        )

        snapshots = []
        for snap in latest_snapshots:
            snapshots.append(
                {
                    "tenant_id": snap.tenant_id,
                    "run_at": snap.run_at,
                    "critical": snap.critical,
                    "high": snap.high,
                    "medium": snap.medium,
                    "low": snap.low,
                    "total_findings": snap.total_findings,
                    "top_findings": snap.top_findings or [],
                    "company_profile": snap.company_profile or {},
                    "narrative_snippet": snap.narrative_snippet or "",
                }
            )

        generated_at = datetime.now(timezone.utc)
        date_label = generated_at.strftime("%a %d %b %Y")
        subject = f"Miragent Portfolio Digest — {date_label}"

        html = build_digest_html(snapshots, generated_at)
        sent = send_digest(to_emails, html, subject)

    except Exception as exc:
        logger.exception("build_and_send_portfolio_digest: unexpected error: %s", exc)
        error = str(exc)[:500]
        sent = False
        to_emails = []
        snapshots = []

    return {
        "sent": sent,
        "recipient_count": len(to_emails),
        "company_count": len(snapshots),
        "error": error,
    }
