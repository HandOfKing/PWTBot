"""Shared result types for the PWT pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MatchResult:
    """Everything process_video() returns; maps directly to db.save_match() args."""
    match: dict                  # recorded_at, source_file, mode, …
    players: list[dict]          # ign, team, slot
    rounds: list[dict]           # round_no, start_s, end_s, winner_team, …
    events: list[dict]           # true_time_s, feed_time_s, event_type, …
    stats: list[dict]            # ign, stat_name, value, round_no
    # diagnostics (not persisted)
    drops: list[dict] = field(default_factory=list)   # Remaining drops
    dropped_rows: list[dict] = field(default_factory=list)  # transient feed rows
