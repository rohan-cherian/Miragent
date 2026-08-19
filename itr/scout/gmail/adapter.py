"""
itr/scout/gmail/adapter.py — import shim for the Gmail adapter.

Task 21 puts ``GmailAdapter`` in ``scout/connectors/gmail.py``, where the other
connector protocol implementations live. Task 22's dispatch
(``scout/canonical/execution.py``) resolves it dynamically as
``scout.gmail.adapter.GmailAdapter``.

Rather than move the class or edit the canonical layer, this module re-exports
it. The dynamic import in execution.py exists so the Task 4 layering lint stays
satisfied — canonical/ must not statically import scout.gmail or
scout.connectors — and that constraint is unaffected by re-exporting here.
"""

from __future__ import annotations

from scout.connectors.gmail import GmailAdapter

__all__ = ["GmailAdapter"]
