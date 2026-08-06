"""
scout/workers/security_hygiene.py — Security Hygiene Worker (Sprint 59)

Operational governance signals with a security dimension. Framed as
operational hygiene — not a CISO audit — so findings are owned by the
PE operating partner and CFO, not the security function.

The five signals:

  1. MFA Enrollment Rate
     What % of platform users have MFA enabled? Low enrollment is an
     operational risk (credential theft = platform access). Data source:
     internal users table (mfa_enabled column).

  2. Inactive Privileged Accounts
     Admin-role users who haven't logged in for > N days. These are
     unreviewed attack surfaces and a SOC 2 finding in the making.
     Data source: Okta / Azure AD connector data in the graph.

  3. API Key Age
     API keys older than 90 days without rotation. Long-lived credentials
     are the #1 source of breach in API-first companies. Data source:
     internal api_keys table.

  4. Orphaned Accounts
     Users active in Okta / Azure AD who have no matching active Person
     record from the HR connector. These are ex-employees who were never
     fully offboarded — their credentials still work.
     Data source: cross-reference identity graph nodes vs HR Person nodes.

  5. Admin Sprawl
     Ratio of admin users to total active users. Industry benchmark: <10%.
     Above 20% = everyone is an admin = no access controls in practice.
     Data source: Okta / Azure AD graph nodes with admin role flag.

Why "operational" not "security":
  Every finding here has a direct operational / cost / governance framing
  that doesn't require the CISO to be in the room:
  - MFA gaps = credential risk = cyber insurance premium risk
  - Inactive admin accounts = orphaned cost + access risk
  - API key age = SOC 2 compliance gap = audit finding
  - Orphaned accounts = unauthorized access = offboarding process failure
  - Admin sprawl = governance gap = PE firm compliance requirement
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class SecurityHygieneWorker(WorkerBase):
    """
    Surfaces operational security hygiene gaps across identity, auth, and
    access control — framed as governance findings, not CISO audit items.

    Reads from both the Neo4j graph (identity connector data) and the
    SQLAlchemy DB (internal users + API keys table).
    """

    WORKER_NAME = "SecurityHygieneWorker"

    def run(
        self,
        tenant_id: str,
        config: dict | None = None,
        db: "Session | None" = None,
    ) -> WorkerResult:
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME, config)
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)

        if not cfg.enabled:
            result.findings.append(Finding(
                title="SecurityHygieneWorker disabled",
                detail="Worker is disabled for this tenant.",
                severity=Severity.LOW,
            ))
            return result

        # ── Run all five hygiene checks ──────────────────────────────────────
        self._check_mfa_enrollment(result, tenant_id, cfg, db)
        self._check_inactive_admins(result, tenant_id, cfg)
        self._check_api_key_age(result, tenant_id, cfg, db)
        self._check_orphaned_accounts(result, tenant_id, cfg)
        self._check_admin_sprawl(result, tenant_id, cfg)

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # 1. MFA ENROLLMENT RATE
    # ─────────────────────────────────────────────────────────────────────────

    def _check_mfa_enrollment(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        db: "Session | None",
    ) -> None:
        """
        Check what % of platform users have MFA enabled.
        Source: internal users table (mfa_enabled column).
        """
        if db is None:
            return

        try:
            from scout.db.models import User
            users = db.query(User).filter(
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
            ).all()
        except Exception as exc:
            logger.warning("SecurityHygieneWorker: MFA check DB error: %s", exc)
            return

        total = len(users)
        if total == 0:
            return

        mfa_enabled = sum(1 for u in users if u.mfa_enabled)
        enrollment_pct = mfa_enabled / total

        low_threshold = cfg.get("mfa_enrollment_low")    # < this = LOW finding
        critical_threshold = cfg.get("mfa_enrollment_critical")  # < this = CRITICAL

        if enrollment_pct < critical_threshold:
            severity = Severity.CRITICAL
        elif enrollment_pct < low_threshold:
            severity = Severity.HIGH
        else:
            return  # Acceptable enrollment rate

        unenrolled = total - mfa_enabled
        result.findings.append(Finding(
            title=f"Low MFA enrollment: {enrollment_pct:.0%} of users protected ({mfa_enabled}/{total})",
            detail=(
                f"{unenrolled} of {total} active platform users have not enrolled in "
                f"two-factor authentication. "
                f"Industry benchmark: ≥90% enrollment. "
                f"Low MFA adoption is the primary driver of account takeover breaches "
                f"and will be flagged in any SOC 2 or cyber insurance assessment."
            ),
            severity=severity,
            data={
                "total_users": total,
                "mfa_enabled_count": mfa_enabled,
                "mfa_enrollment_pct": round(enrollment_pct, 3),
                "unenrolled_count": unenrolled,
                "unenrolled_emails": [
                    u.email for u in users if not u.mfa_enabled
                ][:10],  # cap for payload size
            },
            recommended_action=(
                "Mandate MFA enrollment for all users within 30 days. "
                "Set a Okta / Azure AD policy to block login without MFA. "
                "For Miragent platform users: enable enforcement via Settings → Security."
            ),
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # 2. INACTIVE PRIVILEGED ACCOUNTS
    # ─────────────────────────────────────────────────────────────────────────

    def _check_inactive_admins(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
    ) -> None:
        """
        Flag admin-role identity accounts that haven't logged in for > N days.
        Sources: Okta / Azure AD graph nodes, falling back to mock data.
        """
        inactive_days = cfg.get("inactive_admin_days", 60)
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=inactive_days)

        identity_users = self._get_identity_users(tenant_id)
        if not identity_users:
            return

        # Find admin users with stale last login
        inactive_admins = []
        for user in identity_users:
            if not user.get("is_admin"):
                continue
            last_login_str = user.get("last_login") or user.get("lastLogin") or ""
            if not last_login_str:
                # Never logged in = always flag
                inactive_admins.append(user)
                continue
            try:
                last_login = datetime.fromisoformat(last_login_str.replace("Z", ""))
                if last_login < cutoff:
                    inactive_admins.append(user)
            except (ValueError, TypeError):
                pass

        if not inactive_admins:
            return

        count = len(inactive_admins)
        severity = Severity.CRITICAL if count >= 3 else Severity.HIGH

        result.findings.append(Finding(
            title=f"{count} privileged account{'s' if count > 1 else ''} inactive for >{inactive_days} days",
            detail=(
                f"{count} admin-role identity account{'s' if count > 1 else ''} "
                f"{'have' if count > 1 else 'has'} not logged in for more than {inactive_days} days. "
                f"Inactive privileged accounts are unmonitored attack surfaces. "
                f"SOC 2 CC6.2 requires periodic access reviews — these accounts will fail that control."
            ),
            severity=severity,
            data={
                "inactive_admin_count": count,
                "inactive_threshold_days": inactive_days,
                "accounts": [
                    {
                        "email": u.get("email", u.get("profile", {}).get("email", "unknown")),
                        "last_login": u.get("last_login", u.get("lastLogin", "never")),
                    }
                    for u in inactive_admins
                ],
            },
            recommended_action=(
                f"Review each inactive admin account immediately. "
                f"Deactivate accounts belonging to former employees or unused service accounts. "
                f"Implement a quarterly privileged access review cadence."
            ),
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # 3. API KEY AGE
    # ─────────────────────────────────────────────────────────────────────────

    def _check_api_key_age(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
        db: "Session | None",
    ) -> None:
        """
        Flag API keys that haven't been rotated in > N days.
        SOC 2 and most security frameworks require key rotation every 90 days.
        Source: internal api_keys table.
        """
        if db is None:
            return

        max_age_days = cfg.get("api_key_max_age_days", 90)
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=max_age_days)

        try:
            from scout.db.models import ApiKey
            old_keys = db.query(ApiKey).filter(
                ApiKey.tenant_id == tenant_id,
                ApiKey.is_active.is_(True),
                ApiKey.created_at < cutoff,
            ).all()
        except Exception as exc:
            logger.warning("SecurityHygieneWorker: API key check DB error: %s", exc)
            return

        if not old_keys:
            return

        count = len(old_keys)
        oldest_days = max(
            (datetime.utcnow() - k.created_at).days
            for k in old_keys
        )

        severity = Severity.CRITICAL if oldest_days > max_age_days * 2 else Severity.HIGH

        result.findings.append(Finding(
            title=f"{count} API key{'s' if count > 1 else ''} not rotated in >{max_age_days} days",
            detail=(
                f"{count} active API key{'s are' if count > 1 else ' is'} older than {max_age_days} days "
                f"(oldest: {oldest_days} days). "
                f"Long-lived credentials are the leading cause of API breach. "
                f"SOC 2 CC6.1 and most cyber insurance policies require rotation every 90 days."
            ),
            severity=severity,
            data={
                "stale_key_count": count,
                "max_age_days": max_age_days,
                "oldest_key_days": oldest_days,
                "keys": [
                    {
                        "prefix": k.key_prefix,
                        "label": k.label,
                        "age_days": (datetime.utcnow() - k.created_at).days,
                        "created_by": k.created_by,
                    }
                    for k in old_keys
                ],
            },
            recommended_action=(
                f"Rotate all API keys older than {max_age_days} days immediately. "
                f"Revoke the old key only after confirming the new key is working. "
                f"Set a calendar reminder for 90-day rotation cycles going forward."
            ),
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # 4. ORPHANED ACCOUNTS
    # ─────────────────────────────────────────────────────────────────────────

    def _check_orphaned_accounts(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
    ) -> None:
        """
        Find identity accounts (Okta/Azure AD) with no matching active HR person.
        These are likely ex-employees whose offboarding was incomplete.
        """
        identity_users = self._get_identity_users(tenant_id)
        if not identity_users:
            return

        # Get active HR person emails from graph
        hr_emails: set[str] = set()
        try:
            with self.driver.session() as session:
                rows = session.run(
                    """
                    MATCH (p:Person {tenant_id: $tenant_id, is_active: true})
                    WHERE p.email IS NOT NULL
                    RETURN p.email AS email
                    """,
                    tenant_id=tenant_id,
                )
                hr_emails = {r["email"].lower() for r in rows if r["email"]}
        except Exception as exc:
            logger.debug("SecurityHygieneWorker: HR graph query: %s", exc)
            # Fall back to mock HR emails
            hr_emails = self._mock_hr_emails()

        if not hr_emails:
            return

        # Active identity users not in HR
        orphaned = []
        for user in identity_users:
            if user.get("status") not in ("ACTIVE", "active"):
                continue
            email = (
                user.get("email")
                or user.get("profile", {}).get("email", "")
            ).lower()
            if email and email not in hr_emails:
                orphaned.append(user)

        if not orphaned:
            return

        count = len(orphaned)
        severity = Severity.CRITICAL if count >= 5 else Severity.HIGH

        result.findings.append(Finding(
            title=f"{count} active identity account{'s' if count > 1 else ''} with no HR record (orphaned)",
            detail=(
                f"{count} active Okta/Azure AD account{'s' if count > 1 else ''} "
                f"could not be matched to an active employee in the HR system. "
                f"These are likely ex-employees whose credentials were never revoked — "
                f"a critical offboarding control failure and a direct access risk."
            ),
            severity=severity,
            data={
                "orphaned_count": count,
                "orphaned_accounts": [
                    {
                        "email": (
                            u.get("email")
                            or u.get("profile", {}).get("email", "unknown")
                        ),
                        "status": u.get("status"),
                        "last_login": u.get("last_login", u.get("lastLogin")),
                    }
                    for u in orphaned[:15]
                ],
            },
            recommended_action=(
                "Immediately review each orphaned account with HR and IT. "
                "Deactivate any account belonging to a departed employee. "
                "Implement an automated offboarding trigger: "
                "HR termination event → immediate Okta/Azure AD deactivation."
            ),
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # 5. ADMIN SPRAWL
    # ─────────────────────────────────────────────────────────────────────────

    def _check_admin_sprawl(
        self,
        result: WorkerResult,
        tenant_id: str,
        cfg: ThresholdConfig,
    ) -> None:
        """
        Flag if admin users are >N% of total active identity users.
        Industry benchmark: admins should be <10% of total users.
        """
        identity_users = self._get_identity_users(tenant_id)
        if not identity_users:
            return

        active_users = [u for u in identity_users if u.get("status") in ("ACTIVE", "active")]
        total = len(active_users)
        if total < 5:
            return  # Too small to be meaningful

        admins = [u for u in active_users if u.get("is_admin")]
        admin_count = len(admins)
        admin_pct = admin_count / total

        critical_pct = cfg.get("admin_sprawl_critical_pct", 0.20)
        high_pct = cfg.get("admin_sprawl_high_pct", 0.10)

        if admin_pct > critical_pct:
            severity = Severity.CRITICAL
        elif admin_pct > high_pct:
            severity = Severity.HIGH
        else:
            return

        result.findings.append(Finding(
            title=f"Admin sprawl: {admin_pct:.0%} of users have admin privileges ({admin_count}/{total})",
            detail=(
                f"{admin_count} of {total} active users hold administrator-level access "
                f"({admin_pct:.0%}). "
                f"Industry benchmark: <10% of users should have admin privileges. "
                f"Excessive admin access means no meaningful access controls — "
                f"any compromised account has full system access."
            ),
            severity=severity,
            data={
                "total_active_users": total,
                "admin_count": admin_count,
                "admin_pct": round(admin_pct, 3),
                "admin_emails": [
                    u.get("email", u.get("profile", {}).get("email", "unknown"))
                    for u in admins
                ],
            },
            recommended_action=(
                "Conduct an access review: every admin role should have a documented business justification. "
                "Remove admin access from anyone who doesn't require it for daily work. "
                "Target: <10% admin ratio. Implement just-in-time (JIT) admin elevation "
                "for break-glass scenarios rather than permanent admin assignment."
            ),
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _get_identity_users(self, tenant_id: str) -> list[dict]:
        """
        Pull identity users from the graph (Okta/Azure AD nodes).
        Falls back to mock Okta data if graph has no identity nodes.
        """
        try:
            with self.driver.session() as session:
                rows = session.run(
                    """
                    MATCH (u:IdentityUser {tenant_id: $tenant_id})
                    RETURN u.id AS id, u.email AS email, u.status AS status,
                           u.is_admin AS is_admin, u.last_login AS last_login
                    """,
                    tenant_id=tenant_id,
                )
                result = [dict(r) for r in rows]
                if result:
                    return result
        except Exception:
            pass

        return self._mock_identity_users()

    def _mock_identity_users(self) -> list[dict]:
        """
        Realistic mock identity data with admin flags and last login timestamps.
        Includes deliberately problematic users for demo findings.
        """
        return [
            # Active, MFA enrolled, recent login, non-admin
            {"id": "u001", "email": "s.chen@acmecorp.com",         "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-15T09:23:00"},
            {"id": "u002", "email": "r.krishnamurthy@acmecorp.com","status": "ACTIVE",    "is_admin": True,  "last_login": "2026-05-16T08:55:00"},
            {"id": "u003", "email": "a.foster@acmecorp.com",       "status": "ACTIVE",    "is_admin": True,  "last_login": "2026-05-14T10:30:00"},
            {"id": "u004", "email": "m.johnson@acmecorp.com",      "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-16T08:45:00"},
            {"id": "u005", "email": "p.patel@acmecorp.com",        "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-13T16:30:00"},
            {"id": "u006", "email": "e.vasquez@acmecorp.com",      "status": "ACTIVE",    "is_admin": True,  "last_login": "2026-05-15T09:10:00"},
            {"id": "u007", "email": "j.liu@acmecorp.com",          "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-16T11:00:00"},
            {"id": "u008", "email": "a.mohammed@acmecorp.com",     "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-14T14:22:00"},
            {"id": "u009", "email": "l.nakamura@acmecorp.com",     "status": "ACTIVE",    "is_admin": True,  "last_login": "2026-05-15T07:30:00"},
            # PROBLEM: admin, hasn't logged in since Feb — over 90 days
            {"id": "u010", "email": "t.brennan@acmecorp.com",      "status": "ACTIVE",    "is_admin": True,  "last_login": "2026-02-01T00:00:00"},
            {"id": "u011", "email": "c.mendez@acmecorp.com",       "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-16T13:15:00"},
            {"id": "u012", "email": "d.kim@acmecorp.com",          "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-15T11:00:00"},
            # PROBLEM: admin, last login over 120 days ago — clear risk
            {"id": "u013", "email": "svc-deploy@acmecorp.com",     "status": "ACTIVE",    "is_admin": True,  "last_login": "2025-12-01T00:00:00"},
            # PROBLEM: SUSPENDED but still present (offboarding incomplete)
            {"id": "u014", "email": "b.hartley@acmecorp.com",      "status": "ACTIVE",    "is_admin": False, "last_login": "2026-01-15T00:00:00"},
            # PROBLEM: admin, no MFA, rarely used
            {"id": "u015", "email": "ops-admin@acmecorp.com",      "status": "ACTIVE",    "is_admin": True,  "last_login": "2026-01-20T00:00:00"},
            # Extra non-admin users
            {"id": "u016", "email": "j.wang@acmecorp.com",         "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-10T09:00:00"},
            {"id": "u017", "email": "m.osei@acmecorp.com",         "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-12T14:00:00"},
            {"id": "u018", "email": "f.garcia@acmecorp.com",       "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-11T10:30:00"},
            {"id": "u019", "email": "n.smith@acmecorp.com",        "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-09T16:00:00"},
            {"id": "u020", "email": "y.tanaka@acmecorp.com",       "status": "ACTIVE",    "is_admin": False, "last_login": "2026-05-13T11:00:00"},
        ]

    def _mock_hr_emails(self) -> set[str]:
        """Active HR emails (subset of identity users — some are orphaned)."""
        return {
            "s.chen@acmecorp.com", "r.krishnamurthy@acmecorp.com",
            "a.foster@acmecorp.com", "m.johnson@acmecorp.com",
            "p.patel@acmecorp.com", "e.vasquez@acmecorp.com",
            "j.liu@acmecorp.com", "a.mohammed@acmecorp.com",
            "l.nakamura@acmecorp.com", "t.brennan@acmecorp.com",
            "c.mendez@acmecorp.com", "d.kim@acmecorp.com",
            "j.wang@acmecorp.com", "m.osei@acmecorp.com",
            "f.garcia@acmecorp.com", "n.smith@acmecorp.com",
            "y.tanaka@acmecorp.com",
            # Notably absent: b.hartley, svc-deploy, ops-admin
            # → these will surface as orphaned accounts
        }
