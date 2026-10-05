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

from .. import db
from ..readers import names
from ..readers.counters import CounterReader
from ..readers.feed import FeedReader, LineTracker
from ..readers.screens import ScreenReader, ScoreboardStitcher

ELIM_TYPES = ("kill", "eliminated_knocked")
DEDUPE_WINDOW = 5.0      # A8: collapse same (killer, victim, type) within this many seconds


class ScoreboardWorker:
    """Reads scoreboard rows off the analyser thread (OCR is slow; the round board is up only ~3 s)."""

    def __init__(self, screens):
        self.screens, self.q = screens, queue.Queue()
        self.stitcher, self.roster = None, ()
        threading.Thread(target=self._run, daemon=True).start()

    def start(self, expected, roster):
        self.stitcher, self.roster = ScoreboardStitcher(expected), tuple(roster)

    def submit(self, frame):
        self.q.put(frame)

    def _run(self):
        while True:
            frame = self.q.get()
            try:
                self.stitcher.add(self.screens.read_rows(frame, self.roster))
            finally:
                self.q.task_done()

    def idle(self):
        return self.q.unfinished_tasks == 0

    def finish(self):
        self.q.join()                       # wait for the reads still queued
        return self.stitcher


class Engine:
    def __init__(self, profile, conn, *, roster=(), source_file="live", recorded_at=None, data_dir=None,
                 log=print, on_scoreboard=None):
        self.p, self.conn, self.log = profile, conn, log or (lambda *a: None)
        self.source_file, self.recorded_at = source_file, recorded_at
        self.data_dir = Path(data_dir) if data_dir else db.data_dir()
        self.on_scoreboard = on_scoreboard              # callback(have, expected, done) for the scroll prompt
        self.counters = CounterReader(profile)
        self.screens = ScreenReader(profile, self.counters)
        self.feed = FeedReader(profile)
        f = profile["feed"]
        self.tracker = LineTracker(f["min_seen_s"], f["gap_s"], f["ocr_samples"])
        self.sb_worker = ScoreboardWorker(self.screens)
        for ign in roster: db.get_or_create_player(conn, ign)           # a given roster is remembered
        conn.commit()
        self.known = db.known_names(conn)
        self.team_colors = profile["scoreboard"]["team_colors"]

        self.lm = None
        self.state = "IDLE"                 # IDLE | ROUND_LIVE | ROUND_END | SCOREBOARD | BETWEEN
        self.round_no, self.boards_for_round = 0, set()
        self.players_in_room, self.team_size = None, 2
        self.rem = dict(value=None, cand=None, n=0, left_t=None, first=[])
        self.drops, self.helm_deaths, self.helm = [], [], {}
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
            self._feed(t, frame)
        self.t_cpu += time.perf_counter() - c0

    # ------------------------------------------------------------------ match / rounds
    def _ensure_match(self):
        if self.lm is None:
            self.lm = db.LiveMatch(self.conn, recorded_at=self.recorded_at, source_file=self.source_file,
                                   layout_profile=self.p["name"], pipeline_version="0.2-stageA")
            self.ev_dir = self.data_dir / "evidence" / f"match_{self.lm.id}"
            self.ev_dir.mkdir(parents=True, exist_ok=True)
            self.log(f"match #{self.lm.id} started")
        return self.lm

    def _live(self, t, frame):
        self.banner_absent_since = None
        if self.state != "ROUND_LIVE":
            self._ensure_match()
            self.round_no += 1
            self.lm.start_round(self.round_no, start_s=round(t, 3))
            if self.rem["value"]:
                self.players_in_room = max(self.players_in_room or 0, self.rem["value"])
                self.team_size = max(2, self.players_in_room // 2)
            self.round_info = dict(start=t, score0=self.counters.scores(frame), winner=None, end=None, score=None)
            self.helm = {}
            self.state = "ROUND_LIVE"
            self.log(f"{t:7.2f}s  round {self.round_no} live (players {self.players_in_room})")
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
            if len(r["first"]) >= 2 and r["first"][-1] == r["first"][-2]: r["value"] = v
            return
        if v != r["value"] and r["left_t"] is None: r["left_t"] = t
        if v == r["cand"]: r["n"] += 1
        else: r["cand"], r["n"] = v, 1
        if r["n"] >= 2 and v != r["value"]:
            if v < r["value"]:
                for _ in range(r["value"] - v):
                    self.drops.append(dict(t=r["left_t"], team=None, used=False))
                self.log(f"{r['left_t']:7.2f}s  Remaining {r['value']} -> {v}")
            r["value"], r["left_t"] = v, None                   # an increase = new round reset
        elif v == r["value"]:
            r["left_t"] = None

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
    def _feed(self, t, frame):
        rows = self.feed.rows(frame)
        for line in self.tracker.update(t, rows):
            self._confirm(line)

    def _confirm(self, line):
        """A3: extract names from full-row OCR via roster token matching.
        A7: flag UNRESOLVED instead of dropping.
        A8: dedupe against recent events with the same (killer, victim, type)."""
        lm = self._ensure_match()
        roster = list(self.known) if self.known else []
        k, kc, v, vc, raw_ocr = line.vote(roster)

        # Canonicalise via aliases
        if k:
            k = db.canonical(self.conn, k)
        if v:
            v = db.canonical(self.conn, v)

        # A7: always emit, flag if names unresolved
        if k and v:
            flag = None
        elif k or v:
            flag = "UNRESOLVED"
        else:
            flag = "UNRESOLVED"

        conf = round(min(kc, vc) if (k and v) else max(kc, vc), 2)

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
        rec = dict(feed_t=round(line.first_t, 3), true_t=round(line.first_t, 3),
                   type=line.etype, weapon=line.weapon,
                   killer=k, victim=v, raw_ocr=raw_ocr,
                   conf=conf, source="feed (approx)", drop=None)
        rec["id"] = lm.add_event(dict(
            true_time_s=rec["true_t"], feed_time_s=rec["feed_t"], time_source=rec["source"],
            event_type=rec["type"],
            killer=k, victim=v, killer_raw=k_raw, victim_raw=v_raw,
            weapon=line.weapon, confidence=conf,
            victim_team=self.team_of.get(v) if v else None,
            flag=flag, round_no=self.round_no or None))
        if line.best_crop is not None:
            p = self.ev_dir / f"ev_{rec['id']}.png"
            cv2.imwrite(str(p), line.best_crop)
            self.conn.execute("UPDATE events SET evidence_path=? WHERE id=?",
                              (p.relative_to(self.data_dir).as_posix(), rec["id"]))
            self.conn.commit()
        self.events.append(rec)
        if not (k and v):
            self.pending.append(rec)
        if rec["type"] in ELIM_TYPES:
            self._align(rec)
        self.log(f"{line.first_t:7.2f}s  feed: {k or '?'} --{rec['type']}/{line.weapon or '-'}--> {v or '?'}"
                 f"   (true {rec['true_t']}s, {rec['source']})"
                 + (f"  FLAG {flag}" if flag else ""))

    def _align(self, rec):
        team = self.team_of.get(rec["victim"]) if rec["victim"] else None
        for d in self.drops:
            if d["used"] or d["t"] > rec["feed_t"] + 0.05: continue
            if team and d["team"] and d["team"] != team: continue
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
            self.state, self.sb_started, self.sb_prev, self.sb_kept, self.sb_last_read = "SCOREBOARD", t, None, 0, -1e9
            self.board_round = self.round_no if self.round_no and self.round_no not in self.boards_for_round else None
            self.sb_worker.start(self.players_in_room, self.known)
            self.log(f"{t:7.2f}s  {'round ' + str(self.board_round) if self.board_round else 'match'} scoreboard up")
        cfg = self.p["scoreboard"]
        settled = t - self.sb_started >= cfg.get("settle_s", 0.4)          # skip the fade-in frames
        if settled and (self.screens.table_changed(self.sb_prev, frame)
                        or t - self.sb_last_read >= cfg.get("reread_s", 0.5)):  # re-read the same position to vote
            self.sb_worker.submit(frame.copy())
            self.sb_prev, self.sb_kept, self.sb_last_read = frame, self.sb_kept + 1, t
            if self.lm:
                cv2.imwrite(str(self.ev_dir / f"board_{self.board_round or 'match'}_{self.sb_kept}.jpg"), frame,
                            [cv2.IMWRITE_JPEG_QUALITY, 80])
        if self.on_scoreboard:
            self.on_scoreboard(*self.sb_worker.stitcher.progress())

    def _close_scoreboard(self, t):
        """Board gone: don't wait for the reads still queued (that would stall live capture); save when idle."""
        self.board_pending = dict(round=self.board_round, closed=t, started=self.sb_started, kept=self.sb_kept)
        self.state = "BETWEEN"

    def _save_board(self, wait=False):
        bp, self.board_pending = self.board_pending, None
        st = self.sb_worker.finish()        # returns at once when called because the worker went idle
        t, self.board_round, self.sb_started, self.sb_kept = bp["closed"], bp["round"], bp["started"], bp["kept"]
        lm = self._ensure_match()
        cols = self.p["scoreboard"]["value_cols"]
        elim_col = self.p["scoreboard"]["eliminations_col"]
        rows = st.result(cols)
        stats = []
        new = [f"{r['ign']} (read {r['name_agree']:.0%} consistently)" for r in rows if not r["on_roster"]]
        if new:
            self.notes.append("new player names from the scoreboard, check spelling: " + ", ".join(new))
        for r in rows:
            color = self.team_colors.get(str(r["team"])) if r["team"] is not None else None
            if color:
                self.team_of[r["ign"]] = color
                lm.set_player(r["ign"], color)
            self.known.add(r["ign"])
            for c, v in r["values"].items():
                stats.append(dict(ign=r["ign"], stat_name=c, value=v, confidence=r["agree"][c]))
            stats.append(dict(ign=r["ign"], stat_name="eliminations", value=r["values"].get(elim_col),
                              confidence=r["agree"].get(elim_col)))
        lm.add_stats(stats, round_no=self.board_round)
        have, exp, done = st.progress()
        label = f"round {self.board_round}" if self.board_round else "match"
        if exp and have < exp:
            self.notes.append(f"{label} scoreboard: {have}/{exp} rows captured")
        if self.board_round: self.boards_for_round.add(self.board_round)
        self.log(f"{t:7.2f}s  {label} scoreboard closed: {have}/{exp or '?'} rows "
                 f"({t - self.sb_started:.1f}s on screen, {self.sb_kept} positions read)")
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
                    import re as _re
                    tokens = _re.split(r'\s+', raw)
                    hits = []
                    for tok in tokens:
                        t = _re.sub(r'[^A-Za-z0-9]', '', tok)
                        if len(t) < 4:
                            continue
                        n, sc = names.match(t, roster)
                        if n:
                            hits.append((n, sc))
                    if len(hits) >= 2 and hits[0][0] != hits[-1][0]:
                        if not rec["killer"]:
                            rec["killer"] = upd["killer"] = db.canonical(self.conn, hits[0][0])
                        if not rec["victim"]:
                            rec["victim"] = upd["victim"] = db.canonical(self.conn, hits[-1][0])
                    elif len(hits) == 1 and final:
                        # Only one name found; assign it to whichever role is missing
                        resolved_name = db.canonical(self.conn, hits[0][0])
                        if not rec["killer"]:
                            rec["killer"] = upd["killer"] = resolved_name
                        elif not rec["victim"]:
                            rec["victim"] = upd["victim"] = resolved_name
            if upd:
                resolved = rec["killer"] and rec["victim"]
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
    def finish(self):
        for line in self.tracker.flush(): self._confirm(line)
        if self.state == "SCOREBOARD": self._close_scoreboard(self.last_t)
        if self.board_pending: self._save_board(wait=True)
        if self.state == "ROUND_LIVE": self._end_round(self.last_t)
        if self.lm is None:
            return dict(match_id=None, frames=self.frames, notes=["no round was detected"])
        self._resolve_pending(final=True)
        for rec in self.events:
            for n in (rec["killer"], rec["victim"]):
                if n: self.lm.set_player(n, self.team_of.get(n, ""))
            if rec["victim"] and self.team_of.get(rec["victim"]):
                self.conn.execute("UPDATE events SET victim_team=? WHERE id=?", (self.team_of[rec["victim"]], rec["id"]))
        self.conn.commit()
        self.lm.finish(duration_s=round(self.last_t, 2), team_size=self.team_size,
                       mode="rounds" if self.round_no else None, notes="; ".join(self.notes) or None)
        return dict(match_id=self.lm.id, frames=self.frames, rounds=self.round_no, events=len(self.events),
                    cpu_s=round(self.t_cpu, 1), ms_per_frame=round(1000 * self.t_cpu / max(self.frames, 1), 1),
                    notes=self.notes)
