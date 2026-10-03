"""PWT video processing pipeline — Phase 1 public API.

    from pwt.pipeline import process_video, LayoutProfile

    profile = LayoutProfile.load("gameloop-windowed-1080p")
    result  = process_video("match.mkv", profile, evidence_dir="evidence/")

    # result is a MatchResult; pass straight to db.save_match():
    match_id = db.save_match(conn, result.match, result.players,
                             result.rounds, result.events, result.stats)
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from .decode import decode_frames, video_duration
from .killfeed import run_on_frames as _killfeed
from .counters import run_on_frames as _counters, detect_rounds
from .scoreboard import collect_scoreboards
from .profile import LayoutProfile
from .types import MatchResult

__all__ = ["process_video", "LayoutProfile", "MatchResult"]


# ── reconcile helpers ─────────────────────────────────────────────────────────

def _assign_rounds(events: list[dict], rounds: list[dict]) -> None:
    """Stamp each event with the round_no it falls in (mutates in place)."""
    for ev in events:
        t = float(ev.get("true_time_s", 0))
        ev["round_no"] = None
        for r in rounds:
            if r["start_s"] <= t <= r["end_s"]:
                ev["round_no"] = r["round_no"]
                break


def _reconcile(events: list[dict], stats: list[dict]) -> None:
    """Flag events whose player's scoreboard elim count doesn't match feed count.

    Mismatches add "RECONCILE" to the event flag (doesn't replace LOW_CONF).
    """
    from collections import defaultdict
    board: dict[str, int] = {}
    for s in stats:
        if s["stat_name"] == "eliminations":
            board[s["ign"]] = int(s.get("value") or 0)

    feed_count: dict[str, int] = defaultdict(int)
    for ev in events:
        if ev.get("type") in ("kill", "eliminated_knocked"):
            k = ev.get("killer")
            if k:
                feed_count[k] += 1

    for ev in events:
        k = ev.get("killer")
        if k and k in board:
            if feed_count[k] != board[k]:
                f = ev.get("flag") or ""
                ev["flag"] = (f + "|RECONCILE").lstrip("|")


# ── main entry point ──────────────────────────────────────────────────────────

def process_video(
    path: str | Path,
    profile: LayoutProfile,
    evidence_dir: Optional[str | Path] = None,
    fps: float = 4.0,
    pipeline_version: str = "1.0",
) -> MatchResult:
    """Process one recording and return a MatchResult ready for db.save_match().

    Parameters
    ----------
    path            : path to the MKV / MP4 recording
    profile         : LayoutProfile loaded from JSON
    evidence_dir    : directory to write evidence PNG crops (optional)
    fps             : sample rate (default 4; must match master clock)
    pipeline_version: written to match.pipeline_version
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Recording not found: {path}")

    # 1. Decode all frames once; keep in memory (a 20-min clip @ 4 fps = ~4 800
    #    frames; ~10 MB of 1920×1080 thumbnails if downscaled — fine for now).
    frames = list(decode_frames(path, fps=fps))

    # 2. Scoreboard pass: get roster, team map, and per-round stats
    scoreboards = collect_scoreboards(frames, profile)
    roster: list[str] = []
    team_map: dict[str, str] = {}
    raw_stats: list[dict] = []

    for sb in scoreboards:
        for p in sb["data"]["players"]:
            ign = p["ign"]
            if ign and ign not in roster:
                roster.append(ign)
            if p.get("team") and ign:
                team_map.setdefault(ign, p["team"])
            for stat_name in ("eliminations", "damage_dealt"):
                val = p.get(stat_name)
                if val is not None:
                    raw_stats.append(dict(
                        ign=ign,
                        stat_name=stat_name,
                        value=val,
                        round_no=None,          # filled during round assignment below
                        confidence=p.get("ign_conf", 1.0),
                    ))

    # 3. Kill-feed pass
    ev_dir = Path(evidence_dir) if evidence_dir else None
    feed_events, dropped_rows = _killfeed(frames, profile, roster,
                                          evidence_dir=ev_dir, fps=fps)

    # 4. Round segmentation
    rounds = detect_rounds(frames, profile, fps=fps)

    # Infer team_size from roster length / scoreboard
    team_size = max(2, len(roster) // 2) if roster else 2

    # 5. Counter alignment (Remaining drops → true times)
    aligned_events, drops, _ = _counters(
        frames, feed_events, profile, team_map,
        team_size=team_size, fps=fps,
    )

    # 6. Assign events to rounds
    _assign_rounds(aligned_events, rounds)

    # Assign round_no to stats (index by scoreboard order for now)
    for i, sb in enumerate(scoreboards):
        round_no = i + 1
        for p in sb["data"]["players"]:
            for s in raw_stats:
                if s["ign"] == p["ign"] and s["round_no"] is None:
                    s["round_no"] = round_no

    # 7. Reconcile feed vs scoreboard
    _reconcile(aligned_events, raw_stats)

    # 8. Build final event dicts (db.save_match format)
    events: list[dict] = []
    for ev in aligned_events:
        events.append(dict(
            true_time_s=float(ev["true_time_s"]),
            feed_time_s=float(ev["feed_first_seen_s"]),
            time_source=ev["time_source"],
            event_type=ev["type"],
            killer=ev.get("killer") or None,
            victim=ev.get("victim") or None,
            weapon=ev.get("weapon") or None,
            victim_team=ev.get("victim_team") or None,
            confidence=float(ev.get("name_conf") or 0),
            flag=ev.get("flag") or None,
            round_no=ev.get("round_no"),
            evidence_path=ev.get("evidence_path"),
        ))

    # 9. Build players list from roster + team_map
    players: list[dict] = []
    seen: set[str] = set()
    for ign in roster:
        if ign not in seen:
            players.append(dict(ign=ign, team=team_map.get(ign, "")))
            seen.add(ign)
    # Also include any names seen in the feed but missing from scoreboard
    for ev in events:
        for name in (ev.get("killer"), ev.get("victim")):
            if name and name not in seen:
                players.append(dict(ign=name, team=team_map.get(name, "")))
                seen.add(name)

    # 10. Build match dict
    duration = video_duration(path)
    recorded_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    match = dict(
        recorded_at=recorded_at,
        source_file=str(path),
        duration_s=round(duration, 2),
        mode="rounds" if rounds else "classic",
        team_size=team_size,
        rounds_played=len(rounds),
        winner_team=rounds[-1].get("winner_team") if rounds else None,
        layout_profile=profile.name,
        pipeline_version=pipeline_version,
    )

    stats: list[dict] = raw_stats

    return MatchResult(
        match=match,
        players=players,
        rounds=rounds,
        events=events,
        stats=stats,
        drops=drops,
        dropped_rows=dropped_rows,
    )
