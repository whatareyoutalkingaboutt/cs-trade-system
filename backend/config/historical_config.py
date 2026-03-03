#!/usr/bin/env python3
"""
Historical data collection strategy and defaults.

This module defines collection cadence, retention, and gap detection rules
for the Phase 1 historical data accumulation workflow.
"""

from __future__ import annotations

from typing import Dict, Iterable, Tuple


# Default inputs/outputs
DEFAULT_ITEMS_PATH = "data/test_items.json"
DEFAULT_OUTPUT_DIR = "data/historical"
DEFAULT_PLATFORM = "steam"


# Priority grouping rules (matches data/test_items.json metadata)
PRIORITY_GROUPS: Dict[str, Tuple[int, int]] = {
    "high": (8, 10),
    "medium": (5, 7),
    "low": (1, 4),
}


# Collection cadence by priority group (seconds)
COLLECTION_INTERVAL_SECONDS: Dict[str, int] = {
    "high": 5 * 60,       # every 5 minutes
    "medium": 30 * 60,    # every 30 minutes
    "low": 2 * 60 * 60,   # every 2 hours
}


# History window and retention strategy
ACTIVE_WINDOW_DAYS = 30
RETENTION_DAYS = 365
ARCHIVE_AFTER_DAYS = 90


# Gap detection and fill guidance
GAP_TOLERANCE_MULTIPLIER = 1.5
GAP_FILL_MAX_AGE_HOURS = 6


def priority_to_group(priority: int | None) -> str:
    """Map numeric priority to a group name."""
    if priority is None:
        return "medium"
    for group, (low, high) in PRIORITY_GROUPS.items():
        if low <= priority <= high:
            return group
    return "medium"


def iter_priority_groups(order: Iterable[str] | None = None) -> Iterable[str]:
    """Yield priority groups in desired order."""
    if order:
        return order
    return ("high", "medium", "low")
