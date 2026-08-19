"""
Quick verification: confirm persona aliases were created correctly.
Run: poetry run python scripts/verify_personas.py
"""

import sys
from pathlib import Path

# Ensure the project root (parent of scripts/) is on sys.path so
# `scout` can be imported regardless of how this script is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from scout.config import settings

e = create_engine(settings.database_url)
with e.connect() as c:
    rows = c.execute(text(
        "SELECT p.display_name, a.email, a.verified, a.confidence "
        "FROM itr360.person p "
        "LEFT JOIN itr360.person_email_alias a ON a.person_id = p.id "
        "ORDER BY p.display_name"
    )).fetchall()

for row in rows:
    print(row)
