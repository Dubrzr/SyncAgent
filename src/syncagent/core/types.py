"""Shared types for syncagent.

This module defines types and enums used by both client and server.
"""

from __future__ import annotations

from enum import Enum


class SyncState(str, Enum):
    """Sync state of a machine.

    Used by both client (StatusReporter) and server (StatusHub)
    to track the current synchronization status.
    """

    IDLE = "idle"
    SYNCING = "syncing"
    ERROR = "error"
    OFFLINE = "offline"
