"""
Task 11 — seed personas.

Idempotent — safe to re-run. Each run upserts by a stable natural key
(org name; person external_id; alias email) instead of inserting
duplicates every time.

Consumer Gmail addresses match nothing in a corporate directory, so
Person.primary_email is deliberately left unset here — the identity
hop and org association come entirely from person_email_alias, which
is the point of Task 11.

Persona 3 (Anita Desai) gets a person row but NO alias row, on
purpose: she's the first-contact identity-enrolment test case for
Task 14.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scout.canonical.models import Org, Person, PersonEmailAlias
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))
SOURCE_SYSTEM = "seed"

ORG_NAME = "Northwind Traders"
ORG_TIER = "enterprise"
ORG_EXTERNAL_ID = "org-northwind-traders"

PERSONAS = [
    {
        "env_var": "PERSONA_1_EMAIL",
        "external_id": "persona-1",
        "display_name": "Priya Sharma",
        "job_title": "IT Operations Manager",
        "email": settings.persona_1_email.strip(),
        "create_alias": True,
    },
    {
        "env_var": "PERSONA_2_EMAIL",
        "external_id": "persona-2",
        "display_name": "Marcus Chen",
        "job_title": "Infrastructure Lead",
        "email": settings.persona_2_email.strip(),
        "create_alias": True,
    },
    {
        "env_var": "PERSONA_3_EMAIL",
        "external_id": "persona-3",
        "display_name": "Anita Desai",
        "job_title": "Finance Analyst",
        "email": settings.persona_3_email.strip(),
        "create_alias": False,  # deliberate — first-contact enrolment test case, Task 14
    },
]


def _upsert_org(session: Session, connector_run_id: uuid.UUID, now: datetime) -> Org:
    org = session.execute(
        select(Org).where(Org.tenant_id == TENANT_ID, Org.name == ORG_NAME)
    ).scalar_one_or_none()

    if org is None:
        org = Org(
            id=uuid.uuid4(),
            name=ORG_NAME,
            tier=ORG_TIER,
            domain=None,
            tenant_id=TENANT_ID,
            source_system=SOURCE_SYSTEM,
            external_id=ORG_EXTERNAL_ID,
            is_synthetic=True,
            connector_run_id=connector_run_id,
            observed_at=now,
            valid_from=now,
        )
        session.add(org)
        session.flush()
    else:
        org.tier = ORG_TIER

    return org


def _upsert_person(
    session: Session,
    org: Org,
    persona: dict,
    connector_run_id: uuid.UUID,
    now: datetime,
) -> Person:
    person = session.execute(
        select(Person).where(
            Person.tenant_id == TENANT_ID,
            Person.source_system == SOURCE_SYSTEM,
            Person.external_id == persona["external_id"],
        )
    ).scalar_one_or_none()

    if person is None:
        person = Person(
            id=uuid.uuid4(),
            org_id=org.id,
            display_name=persona["display_name"],
            primary_email=None,
            job_title=persona["job_title"],
            department=None,
            tenant_id=TENANT_ID,
            source_system=SOURCE_SYSTEM,
            external_id=persona["external_id"],
            is_synthetic=True,
            connector_run_id=connector_run_id,
            observed_at=now,
            valid_from=now,
        )
        session.add(person)
        session.flush()
    else:
        person.org_id = org.id
        person.display_name = persona["display_name"]
        person.job_title = persona["job_title"]

    return person


def _upsert_alias(
    session: Session,
    person: Person,
    email: str,
    connector_run_id: uuid.UUID,
    now: datetime,
) -> PersonEmailAlias:
    alias = session.execute(
        select(PersonEmailAlias).where(
            PersonEmailAlias.tenant_id == TENANT_ID,
            PersonEmailAlias.email == email,
        )
    ).scalar_one_or_none()

    evidence = {"method": "seed", "note": "manually verified test persona"}

    if alias is None:
        alias = PersonEmailAlias(
            id=uuid.uuid4(),
            person_id=person.id,
            email=email,
            email_kind="personal",
            verified=True,
            verified_by="seed",
            verified_at=now,
            confidence=0.99,
            evidence=evidence,
            tenant_id=TENANT_ID,
            source_system=SOURCE_SYSTEM,
            external_id=None,
            is_synthetic=True,
            connector_run_id=connector_run_id,
            observed_at=now,
            valid_from=now,
        )
        session.add(alias)
        session.flush()
    else:
        alias.person_id = person.id
        alias.verified = True
        alias.verified_by = "seed"
        alias.verified_at = now
        alias.confidence = 0.99
        alias.evidence = evidence

    return alias


def main() -> int:
    connector_run_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    engine = create_engine(settings.database_url, future=True)

    with Session(engine) as session:
        org = _upsert_org(session, connector_run_id, now)

        summary = []
        for persona in PERSONAS:
            person = _upsert_person(session, org, persona, connector_run_id, now)

            email = persona["email"]
            alias_created = False

            if persona["create_alias"]:
                if email:
                    _upsert_alias(session, person, email, connector_run_id, now)
                    alias_created = True
                else:
                    print(
                        f"WARNING: {persona['display_name']} has no email configured "
                        f"({persona['env_var']} is empty in .env.local) - skipping "
                        f"alias creation."
                    )

            summary.append(
                {
                    "name": persona["display_name"],
                    "email": email or "(none)",
                    "alias_created": alias_created,
                }
            )

        session.commit()

        print()
        print(f"Org: {org.name} (tier={org.tier})")
        print()
        print(f"{'Person':<20} {'Email':<35} {'Alias created':<15}")
        print("-" * 70)
        for row in summary:
            print(f"{row['name']:<20} {row['email']:<35} {row['alias_created']!s:<15}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
