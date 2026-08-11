"""Vendor API emulators built on ``scout.shared`` plumbing."""

from scout.emulators.workday import create_workday_app
from scout.emulators.zendesk import create_zendesk_app

__all__ = ["create_workday_app", "create_zendesk_app"]
