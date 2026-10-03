"""Screen state + scoreboard reading and stitching (brief §3.3, §4.5, §5.5)."""
import cv2, numpy as np
from .digits import DigitReader
from . import names


class ScreenReader:
    def __init__(self, profile, counters):
        self.p, self.counters = profile, counters
        sb = profile["scoreboard"]
        self.hdr = cv2.imread(str(profile.templates / sb["header_template"]), cv2.IMREAD_GRAYSCALE)
        self.band, self.hdr_thresh = sb["header_band"], sb["header_thresh"]
        self.player_col, self.team_col, self.table_y = sb["player_col"], sb["team_col"], sb["table_y"]
        self.value_cols = sb["value_cols"]
        self.digits = DigitReader(profile.templates / "digits_board")

    def is_scoreboard(self, im):
        x0, y0, x1, y1 = self.band
        g = cv2.cvtColor(im[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        s = float(cv2.matchTemplate(g, self.hdr, cv2.TM_CCOEFF_NORMED).max())
        return s >= self.hdr_thresh, round(s, 3)

    def state(self, im):
        """'scoreboard' | 'dimmed' (round-end overlay) | 'live' (banner up) | 'other'."""
        if self.is_scoreboard(im)[0]: return "scoreboard"
        x0, y0, x1, y1 = self.p["game_area"]
        if np.median(cv2.cvtColor(im[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)) < self.p["dim_median_below"]:
            return "dimmed"
        return "live" if self.counters.banner_visible(im) else "other"

    def table_changed(self, prev, cur, thresh=6.0):
        """New scroll position? Mean abs diff of the table area (gray, 1/4 scale)."""
        if prev is None: return True
        y0, y1 = self.table_y
        a, b = (cv2.resize(cv2.cvtColor(x[y0:y1, self.player_col[0] - 10:], cv2.COLOR_BGR2GRAY), None, fx=.25, fy=.25)
                for x in (prev, cur))
        return float(np.abs(a.astype(np.int16) - b).mean()) > thresh

    def _bands(self, im, x0, x1, bright=170, min_h=12, max_h=40, min_prof=4):
        y0, y1 = self.table_y
        prof = (cv2.cvtColor(im[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY) > bright).sum(1)
        out, y = [], 0
        while y < len(prof):
            if prof[y] >= min_prof:
                s = y
                while y < len(prof) and prof[y] >= 1: y += 1
                if min_h <= y - s <= max_h: out.append(((s + y) // 2) + y0)
            y += 1
        return out

    def read_rows(self, im, roster=()):
        """Every visible player row: name (raw + roster match), team number, value cells."""
        teams = [(yc, self.digits.read(im[yc - 20:yc + 20, self.team_col[0]:self.team_col[1]])[0])
                 for yc in self._bands(im, *self.team_col, bright=130, min_prof=2)]
        teams = [(y, v) for y, v in teams if v is not None]
        rows = []
        for yc in self._bands(im, *self.player_col):
            cell = im[yc - 20:yc + 20, self.player_col[0]:self.player_col[1]]
            xs = np.where((cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY) > 150).sum(0) > 0)[0]
            if len(xs): cell = cell[:, max(0, xs[0] - 6):xs[-1] + 6]          # tight crop reads best
            raws = names.ocr_bgr(cell)
            raw = names.consensus(raws)
            name, conf = max((names.match(r, roster) for r in raws), key=lambda m: m[1], default=(None, 0.0))
            vals = {k: self.digits.read(im[yc - 20:yc + 20, a:b])[0] for k, (a, b) in self.value_cols.items()}
            team = min(teams, key=lambda t: abs(t[0] - yc))[1] if teams else None   # team digit sits mid-group
            rows.append(dict(y=yc, raw=raw, raws=raws, name=name, conf=conf, team=team, values=vals))
        return rows


class ScoreboardStitcher:
    """Merge rows seen across scroll positions: one entry per player, majority vote per cell."""

    def __init__(self, expected=None):
        self.expected, self.entries = expected, {}

    def _key(self, r):
        if r["name"] and r["conf"] >= 0.75: return r["name"]
        n = names.norm(r["raw"])
        for k in self.entries:                       # same player read slightly differently: merge
            if names.similar(n, names.norm(k)) >= 0.75: return k
        return n

    def add(self, rows):
        for r in rows:
            k = self._key(r)
            if not k: continue
            e = self.entries.setdefault(k, dict(raws=[], names=[], teams=[], votes={}, seen=0))
            e["seen"] += 1; e["raws"].extend(r.get("raws") or [r["raw"]])
            if r["name"] and r["conf"] >= 0.75: e["names"].append(r["name"])
            if r["team"] is not None: e["teams"].append(r["team"])
            for c, v in r["values"].items():
                if v is not None: e["votes"].setdefault(c, []).append(v)

    def progress(self):
        have = len(self.entries)
        return have, self.expected, self.expected is not None and have >= self.expected

    def result(self, value_cols):
        out = []
        for e in self.entries.values():
            ign = max(set(e["names"]), key=e["names"].count) if e["names"] else names.consensus(e["raws"])
            vals, agree = {}, {}
            for c in value_cols:
                v = e["votes"].get(c, [])
                vals[c] = max(set(v), key=v.count) if v else None
                agree[c] = round(v.count(vals[c]) / len(v), 2) if v else 0.0
            team = max(set(e["teams"]), key=e["teams"].count) if e["teams"] else None
            name_agree = 1.0 if e["names"] else names.agreement(e["raws"], ign)
            out.append(dict(ign=ign, on_roster=bool(e["names"]), name_agree=name_agree, raws=list(e["raws"]),
                            team=team, values=vals, agree=agree, seen=e["seen"]))
        return out
