"""Match highlights: which role each player earned, from the KNOCK rows only (kills do not count).

Pure functions on plain dicts, no Excel and no database, so the rules are tested on a synthetic event set
(tests/test_awards.py). `from_detail` adapts db.match_detail; pwt/export_excel.py writes the result.

Roles (Chirag, 2026-10-10):
  Dominating / Rival  X knocked Y n times. The top 3 one-sided pairs of the match are Dominating, the top 3 pairs
                      that traded knocks most evenly are Rival (ranked, no minimum counts), with Y's share of knockdowns.
  Grenadier           most Grenade knocks.  Molotov specialist: most Molotov knocks (separate from Grenade).
  AR / SMG / LMG / Sniper player, Shotgun specialist
                      one player per class: the most knocks (weapon read) with that class of gun
                      (readers/weapons.py CATEGORY), at least WEAPON_CLASS_MIN of them; the share is shown.
  Driver              Car knocks are credited to the driver, i.e. the killer named on the row.
  Clutch              one per match: the player knocked down EVERY enemy still alive (at least two) while their team
                      had the same number of players alive or fewer (2v2 and two knocks, 3v3 and three, 1v3 and all three).
                      The least certain role: knocks carry the time their feed line appeared (up to ~3.5 s
                      late), the alive count comes from the Remaining-counter drops and the victims' teams.

A knock counts only when both names were read, it is not a self-knock or a Zone row, and (when both teams
are known) the two players are on different teams. The sheet says "based on N of M knocks" so nobody reads
a role as more complete than the feed was: M is the Knock Outs total of the end-of-match board when it was
read, else every knock row seen.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .readers.weapons import CATEGORY

# Everything is per match (Chirag, 2026-10-11): pairs are ranked, not thresholded, and a throwable / weapon-class
# role has one holder. Nothing here has been tuned on more than one match.
TOP_PAIRS = 3                # the top 3 Dominating pairs and the top 3 Rival pairs of the match
LEADER_MIN = {"Grenade": 2, "Molotov": 2, "Car": 1}       # fewest knocks that earn the "most ..." role
WEAPON_ROLE = {"AR": "AR player", "SMG": "SMG player", "LMG": "LMG player", "Sniper": "Sniper player",
               "Shotgun": "Shotgun specialist"}
WEAPON_CLASS_MIN = 3         # knocks with the class before its top player is named (1 sniper knock is not a sniper)
CLUTCH_MIN_ENEMIES = 2             # a clutch knocks down at least this many enemies, all that were left
FEED_LAG_S = 3.5                   # a knock's time is when its feed line appeared: the knock happened up to this much earlier
WEAPON_NOUN = {"AR": "an AR", "SMG": "an SMG", "LMG": "an LMG", "Sniper": "a sniper rifle", "Shotgun": "a shotgun"}
ROLE_ORDER = ["Dominating", "Rival", "Grenadier", "Molotov specialist", "Driver", "Shotgun specialist",
              "AR player", "SMG player", "LMG player", "Sniper player", "Clutch"]
DEATHS = ("kill", "eliminated_knocked")


@dataclass
class Role:
    player: str
    team: str | None
    role: str
    detail: str


@dataclass
class Awards:
    roles: list[Role] = field(default_factory=list)
    knocks_used: int = 0                 # N: knocks the roles are based on
    knocks_seen: int = 0                 # M: board Knock Outs, else all knock rows
    knocks_seen_source: str = ""
    knock_counts: dict = field(default_factory=dict)       # player -> knocks counted
    notes: list = field(default_factory=list)

    def basis(self):
        if self.knocks_seen_source == "board":
            if self.knocks_used > self.knocks_seen:
                return (f"Based on {self.knocks_used} knock rows with both names read; the end-of-match board counts "
                        f"{self.knocks_seen} Knock Outs, so a few rows may be repeats or misreads.")
            return (f"Based on {self.knocks_used} of {self.knocks_seen} knocks read "
                    f"({self.knocks_seen} = Knock Outs on the end-of-match board).")
        if self.knocks_seen_source == "board_partial":
            return (f"Based on {self.knocks_used} knock rows with both names read. The end-of-match board was only partly "
                    f"read (some players or Knock Outs cells missing), so its total of {self.knocks_seen} is a lower bound.")
        return (f"Based on {self.knocks_used} of {self.knocks_seen} knock rows seen "
                f"(the end-of-match board was not read, so the true total is unknown).")


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _leaders(counts, minimum):
    """Players holding the highest count, if it reaches `minimum`."""
    if not counts:
        return [], 0
    top = max(counts.values())
    return ([p for p, n in counts.items() if n == top], top) if top >= minimum else ([], top)


def usable_knocks(events, teams):
    """The knock rows the roles are built from."""
    out = []
    for e in events:
        if e["event_type"] != "knock" or not e["killer"] or not e["victim"] or e["killer"] == e["victim"]:
            continue
        if e["weapon"] == "Zone":
            continue
        tk, tv = teams.get(e["killer"]), teams.get(e["victim"])
        if tk and tv and tk == tv:
            continue
        out.append(e)
    return out


def _round_clutch(round_events, knocks, teams, team_size):
    """{player: (enemies, own_alive_or_None, first_knock_time)} -- each player's biggest clutch in this round.

    Chirag's definition (2026-10-11): one player knocks down EVERY enemy still alive (at least two) while their
    team has the same number of players alive or fewer. 2v2 and two knocks, 3v3 and three, 2v3 or 1v3 and all
    three. For each knock by a player, starting from it: the enemies alive = team_size minus the enemy deaths so
    far; the clutch holds if the player knocked that many different enemies from this knock on, and their team
    was not ahead.

    Deaths (kills and tombstones the Remaining counter confirmed) are placed in time and given a team from the
    victim's player record, else from the row's victim_team. Every doubt goes against the claim:
      - a knock happened up to FEED_LAG_S before its feed line, so a death inside that window may have come
        after it: the knocker's own team is credited only with deaths at least that long before the line, and
        the enemy count is the largest it could have been (so the player must have knocked more people);
      - enemy deaths up to the line all count against "the team was not ahead";
      - a death with no team counts as the enemy's for "the team was not ahead" and as nobody's for the number
        of enemies left."""
    deaths = []
    for e in round_events:
        if e["event_type"] in DEATHS and (e.get("flag") or "") != "NO_DROP":
            team = (teams.get(e["victim"]) if e["victim"] else None) or e.get("victim_team")
            deaths.append((e["true_time_s"], team))
    by_player = defaultdict(list)
    for k in sorted(knocks, key=lambda k: k["true_time_s"]):
        by_player[k["killer"]].append(k)
    out = {}
    for p, ks in by_player.items():
        team = teams.get(p)
        if not team:
            continue
        for i, k in enumerate(ks):
            t = k["true_time_s"]
            own_max = team_size - sum(1 for ts, tm in deaths if tm == team and ts <= t - FEED_LAG_S)
            enemy_min = team_size - sum(1 for ts, tm in deaths if (not tm or tm != team) and ts <= t)
            enemy_max = team_size - sum(1 for ts, tm in deaths if tm and tm != team and ts <= t - FEED_LAG_S)
            unknown = any(not tm and ts <= t for ts, tm in deaths)
            victims = {x["victim"] for x in ks[i:] if teams.get(x["victim"]) != team}
            if enemy_max >= CLUTCH_MIN_ENEMIES and own_max <= enemy_min and len(victims) >= enemy_max:
                if p not in out or enemy_max > out[p][0]:
                    out[p] = (enemy_max, None if unknown else own_max, t)
    return out


def compute(events, teams, team_size=6, board_knocks=None, board_complete=True) -> Awards:
    """events: dicts with event_type, killer, victim, weapon, round_no, true_time_s, victim_team, flag.
    teams: {player: 'blue'|'red'}.  board_knocks: the end-of-match board's Knock Outs total, if read;
    board_complete: False when a player or a Knock Outs cell of that board was missing (the total is then a floor)."""
    events = [dict(e) for e in events]
    knocks = usable_knocks(events, teams)
    all_knocks = sum(1 for e in events if e["event_type"] == "knock")
    res = Awards(knocks_used=len(knocks))
    if board_knocks is not None:
        res.knocks_seen, res.knocks_seen_source = int(board_knocks), "board" if board_complete else "board_partial"
    else:
        res.knocks_seen, res.knocks_seen_source = all_knocks, "rows"
    team = lambda p: teams.get(p)
    add = lambda p, role, detail: res.roles.append(Role(p, team(p), role, detail))

    by_killer = defaultdict(list)
    for k in knocks:
        by_killer[k["killer"]].append(k)
    res.knock_counts = {p: len(v) for p, v in by_killer.items()}
    pairs = Counter((k["killer"], k["victim"]) for k in knocks)
    knocked = Counter(k["victim"] for k in knocks)

    # --- rivals: the pairs that traded knocks most evenly ----------------------------------------------
    # ranked by the smaller side (a 6-5 pair beats a 10-1 pair), then by total; both sides must have knocked
    rivals, seen = [], set()
    for (x, y), a in pairs.items():
        b = pairs.get((y, x), 0)
        if b and (y, x) not in seen:
            seen.add((x, y))
            rivals.append((min(a, b), a + b, x, y, a, b))
    rivals = sorted(rivals, key=lambda r: (-r[0], -r[1], r[2], r[3]))[:TOP_PAIRS]
    rival_pairs = set()
    for _, _, x, y, a, b in rivals:
        rival_pairs |= {(x, y), (y, x)}
        add(x, "Rival", f"Traded knocks with {y}: knocked {y} {_plural(a, 'time')}, was knocked by {y} {_plural(b, 'time')}.")
        add(y, "Rival", f"Traded knocks with {x}: knocked {x} {_plural(b, 'time')}, was knocked by {x} {_plural(a, 'time')}.")
    # --- dominating: the biggest one-sided pairs, rivals excluded --------------------------------------
    dom = [(n - pairs.get((y, x), 0), n, x, y) for (x, y), n in pairs.items()
           if n > pairs.get((y, x), 0) and (x, y) not in rival_pairs]
    for lead, n, x, y in sorted(dom, key=lambda r: (-r[0], -r[1], r[2], r[3]))[:TOP_PAIRS]:
        share = round(100 * n / knocked[y])
        back = pairs.get((y, x), 0)
        add(x, "Dominating", f"Knocked {y} {_plural(n, 'time')} ({share}% of the {knocked[y]} times {y} was knocked)"
                             + (f"; {y} knocked back {back}." if back else "; never knocked back."))

    # --- throwables, car -----------------------------------------------------------------------------
    by_weapon = {w: Counter(k["killer"] for k in knocks if k["weapon"] == w) for w in ("Grenade", "Molotov", "Car")}
    for weapon, role, noun in (("Grenade", "Grenadier", "grenade knock"), ("Molotov", "Molotov specialist", "Molotov knock"),
                               ("Car", "Driver", "car knock")):
        who, n = _leaders(by_weapon[weapon], LEADER_MIN[weapon])
        for p in who:
            tie = " (joint most)" if len(who) > 1 else " (most in the match)"
            tail = ", credited to the driver" if weapon == "Car" else ""
            add(p, role, f"{_plural(n, noun)}{tie}{tail}.")

    # --- weapon classes: one player per class, the most knocks with it (the share is only shown) -----
    reads = {p: [k["weapon"] for k in ks if k["weapon"] in CATEGORY] for p, ks in by_killer.items()}
    winners = {}                                                   # class -> (class knocks, share, player)
    for p, read in reads.items():
        for cat, n in Counter(CATEGORY[w] for w in read).items():
            if cat in WEAPON_ROLE and n >= WEAPON_CLASS_MIN:
                cand = (n, n / len(read), p)
                if cat not in winners or cand[:2] > winners[cat][:2] or (cand[:2] == winners[cat][:2] and p < winners[cat][2]):
                    winners[cat] = cand
    for cat, (n, share, p) in sorted(winners.items()):
        guns = Counter(w for w in reads[p] if CATEGORY[w] == cat).most_common(3)
        add(p, WEAPON_ROLE[cat], f"{n} knocks with {WEAPON_NOUN[cat]}, {round(100 * share)}% of their {len(reads[p])} "
                                 f"with a gun read ({', '.join(f'{g} x{c}' for g, c in guns)}).")

    # --- clutch --------------------------------------------------------------------------------------
    rounds = defaultdict(lambda: ([], []))
    for e in events:
        rounds[e["round_no"]][0].append(e)
    for k in knocks:
        rounds[k["round_no"]][1].append(k)
    clutch = defaultdict(list)                                     # player -> [(enemies, round_no, own_alive)]
    for rn, (evs, ks) in rounds.items():
        if rn is None:
            continue
        for p, (enemies, own, _) in _round_clutch(evs, ks, teams, team_size).items():
            clutch[p].append((enemies, rn, own))
    best = [(max(rs, key=lambda r: (r[0], -(r[2] or team_size))), p, len(rs)) for p, rs in clutch.items()]
    if best:                          # one Clutch per match: the most enemies, then the bigger deficit, then the name
        (enemies, rn, own), p, rounds_n = min(best, key=lambda b: (-b[0][0], b[0][2] or team_size, b[1]))
        size = f" ({own} alive against {enemies})" if own is not None else ""
        more = f" Also in {_plural(rounds_n - 1, 'other round')}." if rounds_n > 1 else ""
        add(p, "Clutch", f"Round {rn}: knocked all {enemies} remaining enemies{size}.{more}")

    order = {r: i for i, r in enumerate(ROLE_ORDER)}
    res.roles.sort(key=lambda r: (r.team or "", r.player.lower(), order.get(r.role, 99)))
    res.notes = [
        res.basis(),
        "Roles use knocks only; kills do not count. A knock counts when the killer and the victim were both read. "
        "Zone knocks belong to no player. Car knocks are credited to the driver.",
        "Weapon roles use the knocks whose gun icon was read; a gun outside the library reads as unknown.",
        "Clutch is the least certain role: it needs the player to have knocked every enemy still alive (at least two) "
        "while their team had the same number alive or fewer. A knock has the time its feed line appeared (up to ~3.5 s "
        "late), while the alive count comes from the Remaining counter and the victims' teams. The knocker's team is "
        "credited only with deaths at least 3.5 s before the feed line and the enemy count is taken at its largest, "
        "and a death with no team read counts for the enemy, so Clutch can miss a real one but should not invent one.",
    ]
    return res


def from_detail(d) -> Awards:
    """Awards for one match from db.match_detail(conn, match_id)."""
    teams = {p["ign"]: p["team"] for p in d["players"]}
    size = d["match"]["team_size"] or 6
    vals = {s["ign"]: s["value"] for s in d["stats"] if s["round_no"] is None and s["stat_name"] == "knock_outs"
            and s["value"] is not None}
    complete = all(p in vals for p in teams)                       # every player of the match has a Knock Outs cell
    return compute(d["events"], teams, team_size=size, board_knocks=int(sum(vals.values())) if vals else None,
                   board_complete=complete)
