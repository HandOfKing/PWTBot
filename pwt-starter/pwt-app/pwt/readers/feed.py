"""Kill feed: find rows, classify icons, read names, and TRACK each line while it is on screen (brief §5.2, §4.3).

Row grammar:  killer · weapon · knock-icon · victim   -> knock
              killer · weapon · victim                -> kill
              killer · tombstone · victim             -> eliminated_knocked
New rows enter the bottom slot and older rows shift up. A line stays about 3.5 s.

A1: Rows are detected by their dark semi-transparent panel (left-padding column
    scan), not by text density.  The parameters live in the profile.
A2: Empty boxes (< 5 alphanumeric characters in OCR output) are rejected.
A3: Names come from full-row OCR + roster token matching, not icon positions.
A6: Each row is OCR'd on every sighting; vote() picks the modal reading.
A9: Weapon icons must score >= weapon_thresh to be named; else weapon = None.
"""
import glob, os, re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import cv2, numpy as np
from .mask import white_mask
from . import names


def load_icons(folder):
    out = {}
    for p in glob.glob(os.path.join(str(folder), "*.png")):
        n = os.path.basename(p)[:-4]
        if n.startswith(("icon_", "weapon_")):
            out[n] = (cv2.imread(p, cv2.IMREAD_GRAYSCALE) > 127).astype(np.float32)
    return out


_SEG = None          # lazily-built glyph segmenter for _looks_like_text


@dataclass
class Row:
    y: int                      # absolute y of the row's top
    h: int                      # row height in pixels
    icons: tuple                # e.g. ('weapon_UMP45', 'icon_knock')
    icon_scores: dict           # {'weapon_UMP45': 0.95, ...}
    row_mask: np.ndarray        # full-row white mask (0/1) for OCR
    crop: np.ndarray            # colour crop of the whole row, for evidence

    @property
    def etype(self):
        if "icon_knock" in self.icons:
            return "knock"
        if "icon_tombstone" in self.icons:
            return "eliminated_knocked"
        return "kill"

    @property
    def weapon(self):
        for n in self.icons:
            if n.startswith("weapon_"):
                if self.icon_scores.get(n, 0) >= self._weapon_thresh:
                    return n[7:]
                return None   # below threshold — A9
        return None

    _weapon_thresh = 0.80       # overridden per-row from the profile


class FeedReader:
    def __init__(self, profile):
        f = profile["feed"]
        self.box = f["box"]
        self.pad = f.get("padding_px", f.get("row_left_x", [105, 140]))
        self.dark_mean = f.get("dark_mean_max", 90)
        self.dark_std = f.get("dark_std_max", 25)
        self.h_min = f.get("row_h_min", 9)
        self.h_max = f.get("row_h_max", 26)
        self.bridge = f.get("bridge", 8)
        self.min_ink_cols = f.get("min_ink_cols", 25)
        # A10: a feed row is TEXT. min_ink_cols rejects an empty panel, but not
        # a bright one -- sky and sunlit scenery ink plenty of columns and sail
        # straight through it, which is why 30% of detections on real footage
        # were a bridge or the horizon. Text has a signature those don't: many
        # separate blobs, all about one height. Off unless the profile asks for
        # it, so footage it has not been measured on keeps its old behaviour.
        self.min_glyphs = f.get("min_glyphs", 0)
        self.glyph_h = (f.get("glyph_h_min", 0), f.get("glyph_h_max", 10 ** 6))
        self.glyph_h_std_max = f.get("glyph_h_std_max", 10 ** 6)
        self.row_detect = f.get("row_detect", "text")   # "text" | "panel"
        self.icon_thresh = f.get("icon_thresh", 0.62)
        self.weapon_thresh = f.get("weapon_thresh", 0.80)
        self.icons = load_icons(profile.templates / "icons")

    def rows(self, frame):
        x0, y0, x1, y1 = self.box
        crop = frame[y0:y1, x0:x1]
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        m = white_mask(crop)
        out = []
        for ry0, ry1 in self._row_bands(m, g):
            # A2: reject empty boxes. The panel detector fires on flat dark
            # scenery too (18-29% of hits on real footage). A real feed row inks
            # 200+ columns; an empty panel inks almost none, so 5 was far too
            # low a bar to catch them.
            row_m = m[max(0, ry0 - 2):ry1 + 2, :]
            col = row_m.sum(0)
            xs = np.where(col > 0)[0]
            if len(xs) < self.min_ink_cols:
                continue
            # A10: does this band actually look like text? See __init__.
            if self.min_glyphs and not self._looks_like_text(m[max(0, ry0 - 2):ry1 + 2, :]):
                continue
            # A3: icons CLASSIFY the event, they NEVER gate row acceptance.
            # templates/ holds only a handful of weapons; a kill with any other
            # gun, or a headshot crosshair, matches nothing. Dropping those rows
            # is what reduced a real 6v6 recording to zero events.
            icons, icon_scores = self._icons(m, ry0, ry1)
            a, b = max(0, ry0 - 2), ry1 + 2
            r = Row(y=ry0 + y0, h=ry1 - ry0, icons=tuple(c[3] for c in icons),
                    icon_scores={c[3]: c[0] for c in icons},
                    row_mask=m[a:b, :].copy(),
                    crop=crop[max(0, ry0 - 8):ry1 + 8, :].copy())
            r._weapon_thresh = self.weapon_thresh
            out.append(r)
        return out

    def _looks_like_text(self, row_mask):
        """A10: is this band text, or is it scenery that happens to be bright?

        Uses the same segmentation the name reader will use downstream, so the
        thresholds mean the same thing in both places. Measured on the 6v6
        recording: this keeps 137/137 rows that resolve to two roster names and
        removes 48 of 75 non-rows, so it costs nothing to use.
        """
        global _SEG
        if _SEG is None:
            from .chars import CharReader
            _SEG = CharReader("")                     # segmentation only, no templates
        hs = [c["h"] for c in _SEG._components(row_mask)]
        if len(hs) < self.min_glyphs:
            return False
        med = float(np.median(hs))
        if not (self.glyph_h[0] <= med <= self.glyph_h[1]):
            return False
        return float(np.std(hs)) <= self.glyph_h_std_max

    def _row_bands(self, m, g):
        """Pick the row detector this footage needs (profile: feed.row_detect).

        'panel' -- scan the panel's flat dark left padding. Required for
          first-person SPECTATOR footage, where the feed overlays moving
          scenery and text density finds the scenery instead of the rows.
          Needs rows far enough apart that the padding goes bright between
          them (measured: min gap 17px in the 6v6 recording).

        'text'  -- the original text-density scan plus a left-alignment
          filter. Right for the 2v2 clip, whose rows sit ~46px apart with a
          panel that stays dark BETWEEN rows, so 'panel' merges them into one
          70px run. Fine there because the background barely moves.

        There is no single setting that serves both. That is what layout
        profiles are for.
        """
        if self.row_detect == "text":
            return self._text_bands(m)
        return self._feed_boxes(g)

    def _text_bands(self, m):
        """Original detector: runs of text density, left-aligned to the feed."""
        prof = m[:, 14:440].sum(1)
        out, y, H = [], 0, len(prof)
        while y < H:
            if prof[y] >= 3:
                s = y
                while y < H and prof[y] >= 2:
                    y += 1
                if self.h_min <= y - s <= self.h_max:
                    col = m[s:y].sum(0)
                    col[:12] = 0
                    xs = np.where(col > 0)[0]
                    lo, hi = self.pad[0] - self.box[0], self.pad[1] - self.box[0]
                    if len(xs) and lo <= xs[0] <= hi:
                        out.append((s, y))
            y += 1
        return out

    def _feed_boxes(self, g):
        """A1: detect feed rows by the dark semi-transparent panel."""
        px0 = self.pad[0] - self.box[0]       # convert absolute to crop-relative
        px1 = self.pad[1] - self.box[0]
        px0 = max(0, px0)
        px1 = min(g.shape[1], px1)
        band = g[:, px0:px1].astype(np.float64)
        dark = ((band.mean(1) < self.dark_mean) &
                (band.std(1) < self.dark_std)).astype(np.uint8)
        # text rows interrupt the padding run — bridge them
        dark = cv2.morphologyEx(dark.reshape(-1, 1), cv2.MORPH_CLOSE,
                                np.ones((self.bridge, 1), np.uint8)).ravel()
        out, y, H = [], 0, len(dark)
        while y < H:
            if dark[y]:
                s = y
                while y < H and dark[y]:
                    y += 1
                if self.h_min <= y - s <= self.h_max:
                    out.append((s, y))
            y += 1
        return out

    def _icons(self, m, y0, y1):
        band = m[max(0, y0 - 6):y1 + 6].astype(np.float32)
        cands = []
        for n, t in self.icons.items():
            if t.shape[0] > band.shape[0] or t.shape[1] > band.shape[1]:
                continue
            r = cv2.matchTemplate(band, t, cv2.TM_CCOEFF_NORMED).max(0)
            for x in np.where(r >= self.icon_thresh)[0]:
                if r[x] == r[max(0, x - 4):x + 5].max():
                    cands.append((float(r[x]), int(x), int(x + t.shape[1]), n))
        keep = []
        for c in sorted(cands, reverse=True):
            if all(c[2] <= k[1] + 3 or c[1] >= k[2] - 3 for k in keep):
                keep.append(c)
        return sorted(keep, key=lambda c: c[1]), {c[3]: c[0] for c in keep}


# ---- Line tracking (A6: multi-frame voting) ----

@dataclass
class Line:
    """One kill-feed line followed across frames."""
    id: int
    icons: tuple
    first_t: float
    last_t: float
    y: int
    h: int
    seen: int = 1
    futures: list = field(default_factory=list)       # Future[str] per OCR sample
    best_crop: np.ndarray = None
    confirmed: bool = False
    row: Row = None

    @property
    def reads(self):
        """All completed full-row OCR strings."""
        return [f.result() for f in self.futures if f.done()]

    @property
    def reads_done(self):
        return all(f.done() for f in self.futures)

    @property
    def etype(self):
        return self.row.etype

    @property
    def weapon(self):
        return self.row.weapon

    def vote(self, roster):
        """A6: pick the best (killer, victim) from all readings.

        Tokenise each reading, match tokens to the roster, pick the reading
        where both names resolved.  Fall back to partial matches.
        Returns (killer, k_score, victim, v_score, raw_ocr).
        """
        candidates = []
        all_raws = []
        for raw in self.reads:
            raw_clean = raw.strip()
            if not raw_clean:
                continue
            all_raws.append(raw_clean)
            tokens = re.split(r'\s+', raw_clean)
            hits = []
            for tok in tokens:
                t = re.sub(r'[^A-Za-z0-9]', '', tok)
                if len(t) < 4:
                    continue
                n, sc = names.match(t, roster)
                if n:
                    hits.append((n, sc))
            if len(hits) >= 2:
                k_name, k_sc = hits[0]
                v_name, v_sc = hits[-1]
                if k_name != v_name:                 # same player can't be both
                    candidates.append((k_name, k_sc, v_name, v_sc, raw_clean))
            elif len(hits) == 1:
                candidates.append((hits[0][0], hits[0][1], None, 0.0, raw_clean))

        raw_consensus = names.consensus(all_raws) if all_raws else ""

        if not candidates:
            return None, 0.0, None, 0.0, raw_consensus

        # Prefer readings where both names resolved
        both = [c for c in candidates if c[0] and c[2]]
        pool = both or candidates

        # Vote: count (killer, victim) pairs
        votes = {}
        for k, ks, v, vs, _ in pool:
            key = (k, v)
            votes[key] = votes.get(key, 0) + min(ks, vs or ks)
        best_key = max(votes, key=votes.get)
        k, v = best_key
        # Get the best individual scores for the winning pair
        k_sc = max((c[1] for c in pool if c[0] == k), default=0.0)
        v_sc = max((c[3] for c in pool if c[2] == v), default=0.0) if v else 0.0
        return k, k_sc, v, v_sc, raw_consensus


class LineTracker:
    """Keeps each feed line's identity while it slides in and moves up the stack, so its names are read
    a few times (not every frame) and it becomes ONE event. Confirm after min_seen_s on screen."""

    def __init__(self, min_seen_s=0.5, gap_s=1.0, ocr_samples=3, workers=2):
        self.min_seen_s, self.gap_s, self.ocr_samples = min_seen_s, gap_s, ocr_samples
        self.lines, self._next = [], 1
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.waiting = []

    def update(self, t, rows):
        """Feed one frame's rows. Returns lines confirmed on this frame."""
        live = [l for l in self.lines if t - l.last_t <= self.gap_s]
        self.lines = live
        used, newly = set(), []
        for r in sorted(rows, key=lambda r: r.y):
            best, best_d = None, 1e9
            for l in live:
                if l.id in used or l.icons != r.icons:
                    continue
                dy = r.y - l.y
                same_slot = abs(dy) <= 4 and t - l.last_t <= 0.25
                moved_up = -60 <= dy <= 4 and abs(r.h - l.h) <= 6
                if same_slot or moved_up:
                    d = abs(dy) + abs(r.h - l.h)
                    if d < best_d:
                        best, best_d = l, d
            if best is None:
                best = Line(self._next, r.icons, t, t, r.y, r.h, row=r)
                self._next += 1
                self.lines.append(best)
                live.append(best)
            else:
                best.last_t, best.y, best.h, best.row = t, r.y, r.h, r
                best.seen += 1
            used.add(best.id)
            # A6: OCR on every sighting (not just first few), up to ocr_samples
            if len(best.futures) < self.ocr_samples and best.seen >= 2:
                best.futures.append(self.pool.submit(names.ocr_mask, r.row_mask))
                best.best_crop = r.crop
            if not best.confirmed and best not in self.waiting \
                    and t - best.first_t >= self.min_seen_s - 1e-6 and best.seen >= 3:
                self.waiting.append(best)
        for l in list(self.waiting):
            if l.futures and l.reads_done:
                l.confirmed = True
                newly.append(l)
                self.waiting.remove(l)
        return newly

    def flush(self):
        """End of source: wait for outstanding reads and return lines that qualified but weren't confirmed."""
        out = []
        for l in self.waiting:
            for f in l.futures:
                f.result()
            l.confirmed = True
            out.append(l)
        self.waiting = []
        return out
