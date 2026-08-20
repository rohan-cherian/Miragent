"""
Show a few REAL KB-article chunks from Qdrant, filtering out any
leftover test data from pytest runs (test points carry acl_tags
starting with 'test-marker-').
"""

import sys
from pathlib import Path

# Ensure the project root (parent of scripts/) is on sys.path so
# `scout` can be imported regardless of how this script is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from scout.config import settings

client = QdrantClient(url=settings.qdrant_url)

# Count total points first
info = client.get_collection(settings.qdrant_collection_name)
print(f"Collection: {settings.qdrant_collection_name}")
print(f"Total points (everything, including any test leftovers): {info.points_count}")
print()

# Scroll through and separate by source_system
kb_count = 0
gmail_count = 0
test_count = 0
other_count = 0

offset = None
sample_kb_points = []

while True:
    points, offset = client.scroll(
        collection_name=settings.qdrant_collection_name,
        limit=100,
        offset=offset,
        with_payload=True,
        with_vectors=False,
    )
    if not points:
        break

    for p in points:
        payload = p.payload or {}
        acl_tags = payload.get("acl_tags", [])
        source_system = payload.get("source_system", "")

        if any(str(tag).startswith("test-marker-") for tag in acl_tags):
            test_count += 1
        elif source_system == "kb_article":
            kb_count += 1
            if len(sample_kb_points) < 5:
                sample_kb_points.append(payload)
        elif source_system == "gmail":
            gmail_count += 1
        else:
            other_count += 1

    if offset is None:
        break

print(f"KB-article chunks (real, source_system='kb_article'): {kb_count}")
print(f"Gmail/email chunks (source_system='gmail'):            {gmail_count}")
print(f"Leftover test-data points (acl_tags has test-marker-):  {test_count}")
print(f"Anything else / unlabeled:                              {other_count}")
print()

print("=== 5 sample REAL KB-article chunks ===")
for i, payload in enumerate(sample_kb_points, 1):
    print(f"\n--- Sample {i} ---")
    print(f"category/problem_class in title area: {payload.get('parent_text', '')[:120]}...")
    print(f"child_text (the actual searchable chunk): {payload.get('child_text', '')[:200]}")
    print(f"kb_article_id: {payload.get('kb_article_id')}")
