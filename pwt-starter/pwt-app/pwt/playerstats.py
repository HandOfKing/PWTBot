"""Per-player knock statistics: who a player knocked most, who knocked them most, and how often they were revived.

Pure functions on plain dicts (tests/test_playerstats.py); `from_detail` adapts db.match_detail and
pwt/export_excel.py writes the "Players" and "Head to head" sheets. KNOCKS only, kills are not used (Chirag,
2026-10-13: a knocked player may be revived, so a knock is not a kill).

Rankings use the knocks where both names were read (the same rows the Highlights roles use, awards.usable_knocks).
"Times knocked" counts every knock row on the player, including ones whose knocker was not read or was the zone,
so it can be larger than the sum of that player's "knocked by" ranking.

Revives (Chirag's rule; computed here but NOT written to the workbook: he parked them on 2026-10-13): a knock was revived when the same player was knocked again later in the round, or was
never finished before the round ended. pwt/schema.sql `v_knock_outcomes` already orders the feed that way:
  revived     knocked again, or knocked / killed someone afterwards: certainly up again       -> "revived"
  eliminated  their next appearance was their own elimination                                  -> "finished"
  unresolved  nothing more about them that round: never finished, so revived by the rule       -> "revived (survived)"
An `unresolved` knock is only "revived (survived)" when no elimination with an unread name followed it in that
round (a NO_FEED_ROW row, on the victim's team or with no team read, from FEED_LAG_S before the knock's feed
line): that row could have been this player's death, and then they were not revived. Those are counted
separately as "unclear" and never added to Revived (flag, never guess).
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .awards import FEED_LAG_S, usable_knocks


@dataclass
class PlayerLine:
    player: str
    team: str | None
    knocks: int = 0                      # knocks made (both names read)
    times_knocked: int = 0               # knock rows on this player, whoever knocked them
    revived: int = 0                     # knocked again / acted again, or survived the round (see module doc)
    revived_confirmed: int = 0           # of those: knocked again or acted again, so certainly up again
    revived_unclear: int = 0
    finished: int = 0                    # knocks after which the player was eliminated
    knocked: list = field(default_factory=list)         # [(opponent, n)] most first
    knocked_by: list = field(default_factory=list)


@dataclass
class Stats:
    players: list = field(default_factory=list)          # [PlayerLine]
    pairs: list = field(default_factory=list)            # [(player, opponent, opponent_team, knocked_them, knocked_by_them)]
    notes: list = field(default_factory=list)


def ranking_text(ranking):
    return " · ".join(f"{name} {n}" for name, n in ranking)


def _rank(counter):
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def compute(events, teams, outcomes) -> Stats:
    """events: dicts with id, event_type, killer, victim, round_no, true_time_s, victim_team, flag.
    teams: {player: team}.  outcomes: {knock event id: 'revived' | 'eliminated' | 'unresolved'}."""
    events = [dict(e) for e in events]
    knocks = usable_knocks(events, teams)
    made, got = defaultdict(Counter), defaultdict(Counter)
    for k in knocks:
        made[k["killer"]][k["victim"]] += 1
        got[k["victim"]][k["killer"]] += 1
    hidden = [e for e in events if e.get("flag") == "NO_FEED_ROW"]       # a death whose victim was not read

    lines = {p: PlayerLine(p, t) for p, t in teams.items()}
    for e in events:
        if e["event_type"] != "knock" or not e["victim"]:
            continue
        ln = lines.setdefault(e["victim"], PlayerLine(e["victim"], teams.get(e["victim"])))
        ln.times_knocked += 1
        out = outcomes.get(e["id"])
        if out == "revived":
            ln.revived += 1
            ln.revived_confirmed += 1
        elif out == "eliminated":
            ln.finished += 1
        elif out == "unresolved":
            doubt = any(h["round_no"] == e["round_no"] and h["true_time_s"] >= e["true_time_s"] - FEED_LAG_S
                        and (not h.get("victim_team") or h["victim_team"] == teams.get(e["victim"]))
                        for h in hidden)
            if doubt:
                ln.revived_unclear += 1
            else:
                ln.revived += 1
    for p, c in made.items():
        lines.setdefault(p, PlayerLine(p, teams.get(p))).knocks = sum(c.values())
    res = Stats()
    for p, ln in lines.items():
        ln.knocked, ln.knocked_by = _rank(made.get(p, {})), _rank(got.get(p, {}))
    res.players = sorted(lines.values(), key=lambda l: (l.team or "", -l.knocks, l.player.lower()))
    opp = {p: set(made.get(p, {})) | set(got.get(p, {})) for p in lines}
    for p in sorted(lines, key=lambda p: (lines[p].team or "", p.lower())):
        for o in sorted(opp[p], key=lambda o: (-made[p][o], -got[p][o], o.lower())):
            res.pairs.append((p, o, teams.get(o), made[p][o], got[p][o]))
    res.notes = [
        f"Knocks only; kills are not used. Rankings come from {len(knocks)} knock rows with both names read.",
        "Times knocked counts every knock row on the player, including knocks by the zone or by someone whose name "
        "was not read, so it can be larger than the total of the player's 'knocked by' ranking.",
    ]
    return res


def from_detail(d) -> Stats:
    teams = {p["ign"]: p["team"] for p in d["players"]}
    return compute(d["events"], teams, {o["knock_id"]: o["outcome"] for o in d["outcomes"]})
