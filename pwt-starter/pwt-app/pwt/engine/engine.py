"""The PWT engine: one frame at a time, identical for live capture and replay (brief §4).

    engine = Engine(profile, conn, source_file="live")
    for t, frame in source.frames():
        engine.process(t, frame)
    summary = engine.finish()

Per frame: screen state -> Remaining / helmets / banner score while a round is live -> kill-feed line tracking
(also during the round-end dim) -> scoreboard rows while a board is up. Every confirmed item is written through
db.LiveMatch immediately, so a crash keeps everything captured so far.
"""
from __future__ import annotations
import queue, threading, time
from pathlib import Path
import cv2

from .. import __version__, db
from ..readers import names
from ..readers.counters import CounterReader
from ..readers.feed import FeedReader, LineTracker, row_names
from ..readers.screens import ScreenReader, ScoreboardStitcher

ELIM_TYPES = ("kill", "eliminated_knocked")
DEDUPE_WINDOW = 5.0      # A8: collapse same (killer, victim, type) within this many seconds
LATE_ROW_S = 8.0         # a feed row first seen this soon after a round starts is the last round's (_row_round)
LATE_ELIM_S = 15.0       # ... and so is a kill row this soon, while its round has had no death yet
LATE_LAG_S = 25.0        # the oldest death a late row (or the end-of-recording pass) may claim
TIMELY_S = 1.5           # a row this soon after a free death is that death's row (_align)
COUNTER_AFTER_S = 1.0   # the Remaining counter may change up to this long AFTER the feed row appears:
                         # the new digit animates in and is unreadable for a few frames. 2026-10-04
                         # 22-55-47 at 24 fps: rows 0.41 s before their drop were flagged NO_DROP.


class ScoreboardWorker:
    """Reads scoreboard rows off the analyser thread (OCR is slow; the round board is up only ~3 s)."""

    def __init__(self, screens):
        self.screens, self.q = screens, queue.Queue()
        self.stitcher, self.roster, self.team_size = None, (), None
        threading.Thread(target=self._run, daemon=True).start()

    def start(self, expected, roster):
        self.stitcher, self.roster = ScoreboardStitcher(expected), tuple(roster)
        self.team_size = expected // 2 if expected else None      # players in the room / 2

    def submit(self, frame):
        self.q.put(frame)

    def _run(self):
        while True:
            frame = self.q.get()
            try:
                self.stitcher.add(self.screens.read_rows(frame, self.roster, self.team_size))
            finally:
                self.q.task_done()

    def idle(self):
        return self.q.unfinished_tasks == 0

    def finish(self):
        self.q.join()                       # wait for the reads still queued
        return self.stitcher


class Engine:
    def __init__(self, profile, conn, *, roster=(), source_file="replay", recorded_at=None, data_dir=None,
                 team_size=6, log=print):
        self.p, self.conn, self.log = profile, conn, log or (lambda *a: None)
        self.source_file, self.recorded_at = source_file, recorded_at
        self.data_dir = Path(data_dir) if data_dir else db.data_dir()
        self.counters = CounterReader(profile)
        self.screens = ScreenReader(profile, self.counters)
        self.feed = FeedReader(profile)
        f = profile["feed"]
        self.tracker = LineTracker(f["min_seen_s"], f["gap_s"], f["ocr_samples"])
        self.sb_worker = ScoreboardWorker(self.screens)
        # The names to match against: this run's roster (and its players' aliases) only. Every name
        # ever stored used to be in this list, misreads included (db.roster_names).
        self.known = db.roster_names(conn, roster) if roster else db.known_names(conn)
        self.team_colors = profile["scoreboard"]["team_colors"]

        self.lm = None
        self.state = "IDLE"                 # IDLE | ROUND_LIVE | ROUND_END | SCOREBOARD | BETWEEN
        self.round_no, self.boards_for_round = 0, set()
        self.round_closed = True            # a board has closed since the last round started
        self.reset_at = None                # Remaining back to a full room after that board: next round's start
        self.board_seq, self.last_board_close, self.match_board = 0, None, False
        self.match_board_min_s = profile["scoreboard"].get("match_board_min_s", 5.0)
        self.off_roster = {}                # scoreboard names not in the roster -> how consistently read
        self.round_starts = []              # (start_s, round_no), for _round_at
        self.players_in_room, self.team_size = None, team_size       # until Remaining says otherwise
        self.rem = dict(value=None, cand=None, n=0, left_t=None, first=[], max=0)
        self.drops, self.helm_deaths, self.helm = [], [], {}
        self.max_align_lag_s = profile.get("max_align_lag_s", 8.0)
        self.round_info = {}
        self.banner_absent_since = None
        self.team_of, self.events, self.pending = {}, [], []
        self.sb_prev, self.sb_kept, self.sb_started = None, 0, None
        self.board_pending = None           # a closed board whose rows are still being read
        self.last_t, self.frames, self.t_cpu = 0.0, 0, 0.0
        self.notes = []

    # ------------------------------------------------------------------ main loop
    def process(self, t, frame):
        c0 = time.perf_counter()
        self.last_t, self.frames = t, self.frames + 1
        st = self.screens.state(frame)
        if self.board_pending and self.sb_worker.idle():
            self._save_board()
        if st == "scoreboard":
            self._scoreboard(t, frame)
        else:
            if self.state == "SCOREBOARD":
                self._close_scoreboard(t)
            if st != "dimmed":
                self._remaining(t, frame)
            if st == "live":
                self._live(t, frame)
            elif self.state == "ROUND_LIVE":
                self._banner_missing(t)
            self._feed(t, frame, fallback=(st != "live"))
        self.t_cpu += time.perf_counter() - c0

    # ------------------------------------------------------------------ match / rounds
    def _ensure_match(self):
        if self.lm is None:
            self.lm = db.LiveMatch(self.conn, recorded_at=self.recorded_at, source_file=self.source_file,
                                   layout_profile=self.p["name"], pipeline_version=__version__)
            self.ev_dir = self.data_dir / "evidence" / f"match_{self.lm.id}"
            self.ev_dir.mkdir(parents=True, exist_ok=True)
            self.log(f"match #{self.lm.id} started")
        return self.lm

    def _start_round(self, t, frame=None, how=None):
        self._ensure_match()
        self.round_no += 1
        self.round_closed, self.reset_at = False, None
        self.lm.start_round(self.round_no, start_s=round(t, 3))
        self.round_starts.append((t, self.round_no))
        if self.rem["value"]:
            self.players_in_room = max(self.players_in_room or 0, self.rem["value"])
            self.team_size = max(2, self.players_in_room // 2)
        self.round_info = dict(start=t, score0=self.counters.scores(frame) if frame is not None else {},
                               winner=None, end=None, score=None, banner_seen=False)
        self.helm = {}
        self.state = "ROUND_LIVE"
        self.log(f"{t:7.2f}s  round {self.round_no} live (players {self.players_in_room})"
                 + (f"  [{how}]" if how else ""))

    def _live(self, t, frame):
        self.banner_absent_since = None
        if self.state != "ROUND_LIVE":
            # A new round needs the last one's board to have come and gone (or nothing yet). The
            # banner hiding for a moment mid-round is the same round, not a new one.
            if self.round_closed or not self.round_no:
                self._start_round(t, frame)
            else:
                self.state = "ROUND_LIVE"
        if not self.round_info.get("banner_seen"):
            self.round_info["banner_seen"] = True
            if not self.round_info.get("score0"): self.round_info["score0"] = self.counters.scores(frame)
        # helmets: a slot is dead after 2 consecutive gray reads
        for team, slots in self.counters.helmets(frame, self.team_size).items():
            for k, s in enumerate(slots):
                key = self.helm.setdefault((team, k), dict(state=None, pend=None))
                if s == "alive":
                    key.update(state="alive", pend=None)
                elif s == "dead" and key["state"] == "alive":
                    if key["pend"] is not None:
                        self._helmet_death(key.pop("pend"), team, k); key.update(state="dead", pend=None)
                    else:
                        key["pend"] = t
        # banner score: who won the round
        sc = self.counters.scores(frame)
        s0 = self.round_info["score0"]
        if self.round_info["winner"] is None:
            for team in ("blue", "red"):
                if sc.get(team) is not None and s0.get(team) is not None and sc[team] > s0[team]:
                    self.round_info.update(winner=team, end=t, score=sc)
                    self.log(f"{t:7.2f}s  round {self.round_no} won by {team} ({sc['blue']}-{sc['red']})")

    def _banner_missing(self, t):
        if not self.round_info.get("banner_seen"):
            return                  # round started by the Remaining reset: its board will end it
        if self.banner_absent_since is None:
            self.banner_absent_since = t
            for (team, k), key in self.helm.items():           # gray read right before the banner vanished
                if key.get("pend") is not None:                # = round-ending death
                    self._helmet_death(key["pend"], team, k); key.update(state="dead", pend=None)
        if self.round_info.get("winner") or t - self.banner_absent_since >= 1.0:
            self._end_round(self.banner_absent_since)

    def _end_round(self, t_hidden):
        ri = self.round_info
        end = ri.get("end") or t_hidden
        sc = ri.get("score") or {}
        self.lm.end_round(self.round_no, end_s=round(end, 3), winner_team=ri.get("winner"),
                          blue_score=sc.get("blue"), red_score=sc.get("red"))
        self.state = "ROUND_END"

    # ------------------------------------------------------------------ counters
    def _remaining(self, t, frame):
        v = self.counters.read_remaining(frame)
        if v is None: return
        r = self.rem
        if r["value"] is None:                                  # first stable reading
            r["first"].append(v)
            if len(r["first"]) >= 2 and r["first"][-1] == r["first"][-2]: r["value"] = r["max"] = v
            return
        if v != r["value"] and r["left_t"] is None: r["left_t"] = t
        if v == r["cand"]: r["n"] += 1
        else: r["cand"], r["n"] = v, 1
        if r["n"] >= 2 and v != r["value"]:
            if v < r["value"]:
                self._round_due(r["left_t"])
                for _ in range(r["value"] - v):
                    self.drops.append(dict(t=r["left_t"], team=None, used=False,
                                           round=self.round_no))
                self.log(f"{r['left_t']:7.2f}s  Remaining {r['value']} -> {v}")
            elif v >= r["max"] and self.round_closed and self.state != "ROUND_LIVE":
                # Back to a full room after a board: the next round is starting (pre-round countdown).
                # It begins here; it is created when it shows life -- the banner, a death or a feed
                # row -- so a recording that stops at this point has no empty round at its end.
                # Backstop for the banner check, which once missed rounds 16-25 of a match.
                self.reset_at = r["left_t"]
            r["value"], r["left_t"], r["max"] = v, None, max(r["max"], v)   # confirmed values only
        elif v == r["value"]:
            r["left_t"] = None

    def _round_due(self, t, feed=False):
        """Something happened at t after a Remaining reset while no round was live: the round the
        reset announced has started, banner seen or not. A death always counts. A feed row counts
        only from LATE_ROW_S after the reset: rows printed after the board belong to the last round
        (see _row_round)."""
        if not (self.round_closed and self.reset_at is not None and t is not None):
            return
        if t >= self.reset_at + (LATE_ROW_S if feed else 0.0):
            self._start_round(self.reset_at, how="Remaining reset")

    def _helmet_death(self, t, team, slot):
        self.helm_deaths.append(dict(t=t, team=team, slot=slot + 1))
        for d in self.drops:                                    # team of the matching Remaining drop
            if d["team"] is None and 0 <= t - d["t"] <= 1.0:
                d["team"] = team
                for ev in self.events:                          # an already-aligned event learns its team
                    if ev.get("drop") is d and ev["victim"] and ev["victim"] not in self.team_of:
                        self.team_of[ev["victim"]] = team
                break

    # ------------------------------------------------------------------ kill feed
    def _feed(self, t, frame, fallback=True):
        # A11's in-run text search runs only off live play. Every feed row the
        # panel detector missed on Video_Project_9 was at a round end (screen
        # fading, rows on screen < 0.5 s); during live play it mostly found
        # in-world nameplates drifting past the feed, and one of those stole a
        # real row's identity (37.9 s) and split it into two events.
        rows = self.feed.rows(frame, fallback=fallback)
        for line in self.tracker.update(t, rows):
            self._confirm(line)

    def _confirm(self, line):
        """A3: extract names from full-row OCR via roster token matching.
        A7: flag UNRESOLVED instead of dropping.
        A8: dedupe against recent events with the same (killer, victim, type)."""
        lm = self._ensure_match()
        self._round_due(line.first_t, feed=True)
        roster = list(self.known) if self.known else []
        k, kc, v, vc, raw_ocr = line.vote(roster)

        # Canonicalise via aliases
        if k:
            k = db.canonical(self.conn, k)
        if v:
            v = db.canonical(self.conn, v)

        # A7: always emit, flag if names unresolved
        if k and v and k == v:
            # A player cannot kill themselves in this mode. feed.vote() screens
            # this out when both names come from one reading, but a name can
            # also arrive later via _resolve_pending, so re-check here. Seen for
            # real on a 720p re-encode: "InnocentDevil --kill--> InnocentDevil",
            # emitted unflagged. Never ship a self-kill as fact.
            flag = "UNRESOLVED"
        elif k and v:
            flag = None
        else:
            flag = "UNRESOLVED"

        conf = round(min(kc, vc) if (k and v) else max(kc, vc), 2)

        if line.short:
            # A row seen for less than min_seen_s (a round end cutting away).
            # Strict: two different roster names, and not the same pair as an
            # event already recorded within the dedupe window -- even of another
            # type, since the first frames of a row sliding in can lack its
            # knock / tombstone icon and would read as a second kill. The one
            # exception is a row that was on screen at the same time (below).
            if not (k and v and k != v):
                self.log(f"{line.first_t:7.2f}s  feed: short row ignored ({raw_ocr!r})")
                return
            seen_at = {t for t, _ in line.hist}
            for prev in reversed(self.events):
                if abs(line.first_t - prev["feed_t"]) > DEDUPE_WINDOW:
                    continue
                if (prev["killer"], prev["victim"]) != (k, v):
                    continue
                # Same pair, different type is a real second row (knock, then
                # the finish) only if the two were on screen TOGETHER -- e.g.
                # 149.1 s: Wolverine's knock row moving up while his kill row
                # on the same player slides in below it.
                together = any(t in seen_at for t, _ in prev.get("seen", ()))
                if prev["type"] == line.etype or not together:
                    self.log(f"{line.first_t:7.2f}s  feed: short row dedupe skip {k} --{line.etype}--> {v}")
                    return

        # A8: dedupe — skip if same (killer, victim, type) within DEDUPE_WINDOW
        if k and v:
            key = (k, v, line.etype)
            for prev in reversed(self.events):
                if line.first_t - prev["feed_t"] > DEDUPE_WINDOW:
                    break
                if (prev["killer"], prev["victim"], prev["type"]) == key:
                    self.log(f"{line.first_t:7.2f}s  feed: dedupe skip {k} --{line.etype}--> {v}")
                    return

        k_raw = k or raw_ocr
        v_raw = v or raw_ocr
        rnd, late = self._row_round(self._round_at(line.first_t), line)
        rec = dict(feed_t=round(line.first_t, 3), true_t=round(line.first_t, 3),
                   type=line.etype, weapon=line.weapon,
                   killer=k, victim=v, raw_ocr=raw_ocr,
                   conf=conf, source="feed (approx)", drop=None, round_no=rnd, late=late,
                   # the line's LIVE sighting list (it keeps growing after this event is
                   # recorded), not the Line itself, which holds image crops
                   seen=line.hist)
        rec["id"] = lm.add_event(dict(
            true_time_s=rec["true_t"], feed_time_s=rec["feed_t"], time_source=rec["source"],
            event_type=rec["type"],
            killer=k, victim=v, killer_raw=k_raw, victim_raw=v_raw,
            weapon=line.weapon, confidence=conf,
            victim_team=self.team_of.get(v) if v else None,
            flag=flag, round_no=rnd))
        if line.best_crop is not None:
            p = self.ev_dir / f"ev_{rec['id']}.png"
            cv2.imwrite(str(p), line.best_crop)
            self.conn.execute("UPDATE events SET evidence_path=? WHERE id=?",
                              (p.relative_to(self.data_dir).as_posix(), rec["id"]))
            self.conn.commit()
        self.events.append(rec)
        if not (k and v):
            self.pending.append(rec)
        if rec["type"] in ELIM_TYPES and (k or v):
            # A row with neither name read (a text-shaped patch of scenery, or a row too dim to
            # read) must not take a death before the named rows have had theirs: 22-55-47 round 20,
            # a junk row at 9.0 s took the 9.67 s death and the real row at 10.0 s became NO_DROP.
            # _settle_eliminations gives it any death left over at the end.
            self._align(rec)
        self.log(f"{line.first_t:7.2f}s  feed: {k or '?'} --{rec['type']}/{line.weapon or '-'}--> {v or '?'}"
                 f"   (true {rec['true_t']}s, {rec['source']})"
                 + (f"  FLAG {flag}" if flag else ""))

    def _round_at(self, t):
        """The round a feed line belongs to: the one live when the line first
        appeared -- not the one live when its OCR happened to finish, which on a
        loaded machine can be the next round."""
        n = None
        for start, no in self.round_starts:
            if start <= t + 1e-6:
                n = no
        return n if n is not None else (self.round_no or None)

    def _row_round(self, rnd, line):
        """(round, late) for a feed row. The feed prints a team wipe one row at a time, ~2.5 s
        apart, and the board interrupts it: the last rows of a round appear after its board, when
        the next round has begun (Video_Project_13 126.3 / 126.7 s: deaths of the round-16 wipe at
        115.0 s, first seen after round 17's banner). Such a row belongs to the round before:
          - any row first seen within LATE_ROW_S of its round's start (nobody has met yet), and
          - a kill row within LATE_ELIM_S while its round has had no death: the counter drops
            before the feed prints a death, so a kill row before any drop is not this round's.
        A late row may claim an unclaimed death of its round up to LATE_LAG_S old (_align)."""
        if not rnd or rnd < 2:
            return rnd, False
        start = next((s for s, n in self.round_starts if n == rnd), None)
        if start is None:
            return rnd, False
        since = line.first_t - start
        if since <= LATE_ROW_S:
            return rnd - 1, True
        if line.etype in ELIM_TYPES and since <= LATE_ELIM_S and not any(
                d["round"] == rnd and d["t"] is not None and d["t"] <= line.first_t + COUNTER_AFTER_S
                for d in self.drops):
            return rnd - 1, True
        return rnd, False

    def _align(self, rec):
        """Give an elimination its true time from the matching Remaining drop.

        Two guards, both learned from a real 6v6 recording:

        - **Same round only.** Unused drops pile up when several players die at
          once (a team wipe drops Remaining by 3 in one frame, but only some of
          those produce a feed row we could read). Without this, a round-2 row
          reached back and claimed a round-1 drop 40s earlier.
        - **Max lag.** The feed trails the event by up to ~3.5s, so a drop far
          older than the feed line is not that line's drop. Beyond the limit we
          keep the feed time and flag it, rather than assert a wrong one.

        Team filtering (via helmets) would catch most of this on its own, but
        helmets are not measured for 6v6 yet, so these guards carry the load.
        """
        team = self.team_of.get(rec["victim"]) if rec["victim"] else None
        ok = []
        for d in self.drops:
            if d["used"] or d["t"] > rec["feed_t"] + COUNTER_AFTER_S: continue
            if d.get("round") is not None and d["round"] != rec.get("round_no", self.round_no): continue
            if rec["feed_t"] - d["t"] > (LATE_LAG_S if rec.get("late") else self.max_align_lag_s): continue
            if team and d["team"] and d["team"] != team: continue
            ok.append(d)
        # A row normally appears within a second of ITS death (22-55-47, round 20: 28.3 -> 28.5,
        # 37.5 -> 37.8, 39.5 -> 40.0). When a death just before the row is free, it is this row's.
        # Oldest-first only for backlogged rows (a team wipe prints ~2.5 s apart), and it used to
        # pair a row with an older death whose own row was never read, shifting every later pair.
        timely = [d for d in ok if rec["feed_t"] - d["t"] <= TIMELY_S]
        if timely:
            ok = [max(timely, key=lambda d: (d["t"] <= rec["feed_t"], d["t"]))]
        for d in ok[:1]:
            d["used"], rec["drop"], rec["true_t"] = True, d, d["t"]
            rec["source"] = "Remaining drop + helmet" if d["team"] else "Remaining drop"
            self.lm.update_event_time(rec["id"], round(d["t"], 3), rec["source"])
            if d["team"] and rec["victim"]: self.team_of.setdefault(rec["victim"], d["team"])
            return

    # ------------------------------------------------------------------ scoreboards
    def _scoreboard(self, t, frame):
        if self.state != "SCOREBOARD":
            if self.board_pending: self._save_board(wait=True)         # back-to-back boards (rare)
            if self.state == "ROUND_LIVE":
                self._end_round(t)
            self.board_seq += 1
            self.state, self.sb_started, self.sb_prev, self.sb_kept, self.sb_last_read = "SCOREBOARD", t, None, 0, -1e9
            self.sb_worker.start(self.players_in_room or 2 * self.team_size, self.known)
            self.log(f"{t:7.2f}s  scoreboard up")
        cfg = self.p["scoreboard"]
        settled = t - self.sb_started >= cfg.get("settle_s", 0.4)          # skip the fade-in frames
        if settled and (self.screens.table_changed(self.sb_prev, frame)
                        or t - self.sb_last_read >= cfg.get("reread_s", 0.5)):  # re-read the same position to vote
            self.sb_worker.submit(frame.copy())
            self.sb_prev, self.sb_kept, self.sb_last_read = frame, self.sb_kept + 1, t
            if self.lm:
                cv2.imwrite(str(self.ev_dir / f"board_{self.board_seq}_{self.sb_kept}.jpg"), frame,
                            [cv2.IMWRITE_JPEG_QUALITY, 80])

    def _close_scoreboard(self, t, at_end=False):
        """Board gone: decide whose board it was, wait for its queued reads and save it now.

        Which board: a round board is up ~2.9 s (the game's own "Next Round" countdown); the
        end-of-match board stays until the person recording leaves it, and they scroll it. So a
        board up >= match_board_min_s, or still up when the recording ends, is the match board.
        A round board whose round already has one belongs to a round nobody saw start; that
        round is created now rather than the board being filed as the match board, which is
        what happened to 4 round boards on 2026-10-04 22-55-47.

        Saving waits for the reads still queued. It used to happen "whenever the worker went
        idle", a wall-clock moment, and saving sets team_of, which _align filters on: the same
        file gave different tables depending on CPU load (handoff 2026-10-05 section 5).
        """
        if at_end or t - self.sb_started >= self.match_board_min_s:
            rnd = None
        elif self.round_no and self.round_no not in self.boards_for_round:
            rnd = self.round_no
        else:
            rnd = self._missed_round(self.sb_started)
        self.round_closed, self.last_board_close = True, t
        self.board_pending = dict(round=rnd, closed=t, started=self.sb_started, kept=self.sb_kept)
        self.state = "BETWEEN"
        self._save_board(wait=True)

    def _missed_round(self, board_t):
        """A round board for a round never seen starting (no banner, no Remaining reset). The
        round ran from the previous board to this one: create it, and move the drops and events
        of that stretch into it so _align and the knock credit work within the right round."""
        start = (self.reset_at if self.reset_at is not None
                 else self.last_board_close if self.last_board_close is not None else 0.0)
        self._ensure_match()
        self.round_no += 1
        no = self.round_no
        self.lm.start_round(no, start_s=round(start, 3))
        self.lm.end_round(no, end_s=round(board_t, 3))
        self.round_starts.append((start, no)); self.round_starts.sort()
        for d in self.drops:
            if d["t"] is not None and d["t"] >= start: d["round"] = no
        moved = [e for e in self.events if e["feed_t"] >= start and e.get("round_no") != no]
        for e in moved: e["round_no"] = no
        if moved: self.lm.move_events([e["id"] for e in moved], no)
        self.log(f"{start:7.2f}s  round {no}: start not seen, found by its board at {board_t:.2f}s "
                 f"({len(moved)} feed rows moved into it)")
        self.notes.append(f"round {no} was found only by its scoreboard (its start was not seen)")
        return no

    def _save_board(self, wait=False):
        bp, self.board_pending = self.board_pending, None
        st = self.sb_worker.finish()        # returns at once when called because the worker went idle
        t, rnd, started, kept = bp["closed"], bp["round"], bp["started"], bp["kept"]
        lm = self._ensure_match()
        cols = self.p["scoreboard"]["value_cols"]
        elim_col = self.p["scoreboard"]["eliminations_col"]
        rows = st.result(cols)
        stats = []
        for r in rows:
            if not r["on_roster"]:
                # Not in this run's roster: kept on the board (its numbers are real), never used to
                # resolve kill-feed names, and reported so the right spelling can be added.
                self.off_roster[r["ign"]] = max(self.off_roster.get(r["ign"], 0.0), r["name_agree"])
            color = self.team_colors.get(str(r["team"])) if r["team"] is not None else None
            if color:
                self.team_of[r["ign"]] = color
                lm.set_player(r["ign"], color)
            for c, v in r["values"].items():
                stats.append(dict(ign=r["ign"], stat_name=c, value=v, confidence=r["agree"][c]))
            stats.append(dict(ign=r["ign"], stat_name="eliminations", value=r["values"].get(elim_col),
                              confidence=r["agree"].get(elim_col)))
        lm.add_stats(stats, round_no=rnd)
        have, exp, done = st.progress()
        label = f"round {rnd}" if rnd else "match"
        if rnd: self.boards_for_round.add(rnd)
        else:
            self.match_board = True
            if exp and have < exp:
                self.notes.append(f"end-of-match scoreboard: {have}/{exp} players read (scroll it slowly, top to bottom)")
        self.log(f"{t:7.2f}s  {label} scoreboard: {have}/{exp or '?'} rows "
                 f"({t - started:.1f}s on screen, {kept} positions read)")
        self._resolve_pending()

    def _resolve_pending(self, final=False):
        """Try to resolve pending events now that we have more names from the scoreboard."""
        still = []
        roster = list(self.known)
        for rec in self.pending:
            upd = {}
            if not rec["killer"] or not rec["victim"]:
                # Re-parse the raw OCR against the updated roster
                raw = rec.get("raw_ocr", "")
                if raw and roster:
                    # Same parser as the feed itself. A lone name gets a role only
                    # when its position in the reading settles it -- it used to be
                    # handed to whichever role was empty, which made victims into
                    # killers. Never complete a row into a self-kill: one name is
                    # evidence of half a row, not of a complete one.
                    k, _, v, _ = row_names(raw, roster)
                    k = db.canonical(self.conn, k) if k else None
                    v = db.canonical(self.conn, v) if v else None
                    if k and v:
                        if not rec["killer"] and k != rec["victim"]:
                            rec["killer"] = upd["killer"] = k
                        if not rec["victim"] and v != rec["killer"]:
                            rec["victim"] = upd["victim"] = v
                    elif final:
                        if k and not rec["killer"] and k != rec["victim"]:
                            rec["killer"] = upd["killer"] = k
                        if v and not rec["victim"] and v != rec["killer"]:
                            rec["victim"] = upd["victim"] = v
            if upd:
                resolved = (rec["killer"] and rec["victim"]
                            and rec["killer"] != rec["victim"])
                db.correct_event(self.conn, rec["id"], **upd)
                self.conn.execute("UPDATE events SET reviewed=0, flag=? WHERE id=?",
                                  (None if resolved else "UNRESOLVED", rec["id"]))
                self.conn.commit()
                if rec.get("drop") and rec["drop"]["team"] and rec["victim"]:
                    self.team_of.setdefault(rec["victim"], rec["drop"]["team"])
            if not (rec["killer"] and rec["victim"]):
                still.append(rec)
        self.pending = still

    # ------------------------------------------------------------------ end
    def _settle_eliminations(self):
        """End of the recording: every round is over, so each round's unclaimed deaths are known.

        A kill row that found no drop within max_align_lag_s takes the earliest unclaimed death of
        its round up to LATE_LAG_S before it -- the last rows of a wipe can be printed 15 s after the
        deaths (2026-10-04 22-55-47 round 17: deaths at 1264.0 s, rows at 1275-1279 s). Without
        this the row stayed unmatched AND its death became a NO_FEED_ROW: one death, two rows.

        A kill row left with no death to claim is one the Remaining counter never saw: a repeat of
        a row already counted, or a knock row read as a kill. It is kept, flagged NO_DROP, and not
        counted -- the counter, read on every frame, is the authority on how many died.
        """
        n = 0
        for rec in self.events:
            if rec["type"] not in ELIM_TYPES or rec.get("drop") is not None or rec.get("id") is None:
                continue
            for d in self.drops:
                if d["used"] or d["t"] is None or d["t"] > rec["feed_t"] + COUNTER_AFTER_S: continue
                if rec["feed_t"] - d["t"] > LATE_LAG_S: continue
                if d.get("round") is not None and d["round"] != rec.get("round_no"): continue
                d["used"], rec["drop"], rec["true_t"] = True, d, d["t"]
                rec["source"] = "Remaining drop + helmet" if d["team"] else "Remaining drop"
                self.lm.update_event_time(rec["id"], round(d["t"], 3), rec["source"])
                if d["team"] and rec["victim"]: self.team_of.setdefault(rec["victim"], d["team"])
                break
            else:
                self.conn.execute("UPDATE events SET flag='NO_DROP' WHERE id=?", (rec["id"],))
                rec["flag"] = "NO_DROP"
                n += 1
                self.log(f"{rec['feed_t']:7.2f}s  {rec['killer'] or '?'} --{rec['type']}--> {rec['victim'] or '?'}"
                         f"  FLAG NO_DROP (no death on the Remaining counter for it; not counted)")
        self.conn.commit()
        if n:
            self.notes.append(f"{n} kill row(s) had no death on the Remaining counter (repeats or misread "
                              f"icons) and are flagged NO_DROP, not counted")

    def _emit_unclaimed_drops(self):
        """A13: a Remaining drop no feed row ever claimed is still an elimination.

        The counter is an independent signal (ARCHITECTURE §3): it sees every
        death whether or not the kill feed printed a readable line for it. Those
        drops were being discarded, so a death the game never announced -- four
        at once in a team collapse, or a row too occluded to read -- vanished
        from the table with nothing to show it had happened. Measured on
        Video_Project_9: 14 drops, 8 attributed, 6 silently dropped.

        Emitted with NO killer and NO victim. That is the point. The roster
        could supply a plausible name and the margin rule would even accept it,
        but inventing an attribution here would corrupt the per-player counts
        with kills nobody made -- invariant 1, flag never guess. A row saying
        "someone on red died at 146.75s and the feed never said who" is
        information; a guessed name is damage.

        Run after _resolve_pending(final=True) so a late resolution still gets
        first claim on its drop.
        """
        if not self.lm:
            return
        n = 0
        for d in self.drops:
            if d["used"]:
                continue
            t = round(d["t"], 3)
            rec = dict(feed_t=t, true_t=t, type="kill", weapon=None,
                       killer=None, victim=None, raw_ocr=None, conf=None,
                       source="Remaining drop (no feed row)", drop=d)
            rec["id"] = self.lm.add_event(dict(
                true_time_s=t, feed_time_s=t,
                time_source=rec["source"], event_type="kill",
                killer=None, victim=None, killer_raw=None, victim_raw=None,
                weapon=None, confidence=None, victim_team=d.get("team"),
                flag="NO_FEED_ROW", round_no=d.get("round") or self.round_no or None))
            self.events.append(rec)
            d["used"] = True
            n += 1
            self.log(f"{t:7.2f}s  unattributed elimination"
                     f"{' (team ' + d['team'] + ')' if d.get('team') else ''}"
                     f"  FLAG NO_FEED_ROW")
        if n:
            self.notes.append(f"{n} elimination(s) seen by the Remaining counter had no "
                              f"readable feed row and are flagged NO_FEED_ROW")

    def finish(self):
        for line in self.tracker.flush(): self._confirm(line)
        if self.state == "SCOREBOARD": self._close_scoreboard(self.last_t, at_end=True)
        if self.board_pending: self._save_board(wait=True)
        if self.state == "ROUND_LIVE": self._end_round(self.last_t)
        if self.lm is None:
            return dict(match_id=None, frames=self.frames, notes=["no round was detected"])
        self._resolve_pending(final=True)
        self._settle_eliminations()
        self._emit_unclaimed_drops()
        if self.off_roster:
            self.notes.append("on the scoreboard but not in the player list (add the exact in-game spelling and "
                              "run again): " + ", ".join(sorted(self.off_roster)))
        if not self.match_board:
            self.notes.append("no end-of-match scoreboard: keep recording on the final board and scroll it slowly")
        for rec in self.events:
            for n in (rec["killer"], rec["victim"]):
                if n: self.lm.set_player(n, self.team_of.get(n, ""))
            if rec["victim"] and self.team_of.get(rec["victim"]):
                self.conn.execute("UPDATE events SET victim_team=? WHERE id=?", (self.team_of[rec["victim"]], rec["id"]))
        self.conn.commit()
        # A12: a read that failed is not a box with no text in it. Surface it,
        # or a broken OCR engine looks exactly like a quiet match.
        from ..readers import names as _names
        ns = _names.stats
        if ns["no_engine"]:
            self.notes.append(f"NO OCR ENGINE: {ns['no_engine']} name reads returned nothing because "
                              f"there are no character templates and tesseract was not found - "
                              f"names in this run are not trustworthy")
        if ns["launch_error"]:
            self.notes.append(f"tesseract failed to start on {ns['launch_error']} read(s)")
        if ns["timeout"]:
            self.notes.append(f"{ns['timeout']} name read(s) timed out and were lost "
                              f"(machine under load); rerunning may give a different table")
        self.lm.finish(duration_s=round(self.last_t, 2), team_size=self.team_size,
                       mode="rounds" if self.round_no else None, notes="; ".join(self.notes) or None)
        return dict(match_id=self.lm.id, frames=self.frames, rounds=self.round_no, events=len(self.events),
                    fragments_merged=self.tracker.merged,
                    cpu_s=round(self.t_cpu, 1), ms_per_frame=round(1000 * self.t_cpu / max(self.frames, 1), 1),
                    notes=self.notes)
