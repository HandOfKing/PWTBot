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
        # A11: rows inside an over-tall dark run, found by their text. Off unless
        # the profile sets ink_fallback (see _ink_rows).
        self.ink_fallback = f.get("ink_fallback", False)
        self.ink_row_h = f.get("ink_row_h", 34)
        self.ink_band_h = f.get("ink_band_h", [8, 26])
        self.ink_start_x = f.get("ink_start_x", [114, 130])
        self.icon_thresh = f.get("icon_thresh", 0.62)
        self.weapon_thresh = f.get("weapon_thresh", 0.80)
        self.icons = load_icons(profile.templates / "icons")

    def rows(self, frame, fallback=True):
        """Feed rows on this frame. fallback=False switches the A11 in-run text
        search off for this frame (the engine uses it only off live play)."""
        x0, y0, x1, y1 = self.box
        crop = frame[y0:y1, x0:x1]
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        m = white_mask(crop)
        out = []
        for band in self._row_bands(m, g, fallback):
            ry0, ry1 = band[:2]
            via_ink = len(band) > 2                  # found by the A11 fallback
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
            if via_ink and not icons:
                # A11 rows only. The fallback also finds in-world nameplates
                # ("1 | RGODxEMPEROR" on a blue bar) drifting across the feed's
                # left edge; on Video_Project_9 every junk row it added matched
                # no icon, and every real feed row it added matched a gun, knock
                # or tombstone. Panel-detected rows are never gated (A3): this
                # can only decline a row that, without the fallback, nobody saw.
                continue
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

    def _row_bands(self, m, g, fallback=True):
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
        return self._feed_boxes(g, m if fallback else None)

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

    def _feed_boxes(self, g, m=None):
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
                elif y - s > self.h_max and self.ink_fallback and m is not None:
                    out += self._ink_rows(m, s, y)
            y += 1
        return out

    def _ink_rows(self, m, s, e):
        """A11: rows inside a dark run too tall to be one row.

        The panel detector needs scenery that is brighter than the panel's
        padding. Against a dark wall, at night, or in the round-end dim the
        whole feed band is one dark run and it found NOTHING -- which is where
        all six NO_FEED_ROW eliminations in Video_Project_9 were (rows plainly
        readable, e.g. 152.0 s and 155.75 s). Inside such a run, find the rows
        by their text instead: a band of white-mask ink of text height whose
        ink starts where a left-aligned killer name starts (most in-world
        nameplates drifting through the band start far to the right; one at
        the left edge is declined in rows() for matching no icon). The box is
        centred on the text with the panel's usual height, so tracking sees
        the same geometry whichever detector found the row. Everything
        downstream (ink, text-shape, OCR, roster) still has to accept it.
        """
        x0 = self.box[0]
        a, b = self.ink_start_x[0] - x0, self.ink_start_x[1] - x0
        prof = m[s:e, 10:440].sum(1)
        out, y, H = [], 0, len(prof)
        while y < H:
            if prof[y] >= 3:
                t0 = y
                while y < H and prof[y] >= 2:
                    y += 1
                th = y - t0
                if self.ink_band_h[0] <= th <= self.ink_band_h[1] and m[s + t0:s + y, a:b].any():
                    c = s + t0 + th // 2
                    r0 = max(0, c - self.ink_row_h // 2)
                    out.append((r0, min(m.shape[0], r0 + self.ink_row_h), "ink"))
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


# ---- Names in one OCR reading ----

def row_names(raw, roster):
    """(killer, k_score, victim, v_score) from one full-row OCR reading.

    Two roster names: first is the killer, last the victim (the row reads
    left to right: killer, icons, victim).

    ONE name: its role comes from where it sits in the reading, and only when
    that is unambiguous -- the first of several tokens is the killer, the last
    of several is the victim. Otherwise no role is assigned. It used to be put
    in the killer slot unconditionally, which turned a row caught mid slide-in
    ("ine <gun> PARAbloodthirs", killer still off screen) into
    "PARAbloodthirs --kill--> ?" and credited the victim with an elimination.
    """
    toks = [re.sub(r'[^A-Za-z0-9]', '', t) for t in raw.split()]
    toks = [t for t in toks if t]
    hits = []
    for i, t in enumerate(toks):
        if len(t) < 4:
            continue
        n, sc = names.match(t, roster)
        if n:
            hits.append((i, n, sc))
    if len(hits) >= 2:
        if hits[0][1] == hits[-1][1]:               # same player can't be both
            return None, 0.0, None, 0.0
        return hits[0][1], hits[0][2], hits[-1][1], hits[-1][2]
    if len(hits) == 1 and len(toks) > 1:
        i, n, sc = hits[0]
        if i == 0:
            return n, sc, None, 0.0
        if i == len(toks) - 1:
            return None, 0.0, n, sc
    return None, 0.0, None, 0.0


# ---- Line tracking (A6: multi-frame voting) ----

def icon_key(icons):
    """Identity of a row's icons for tracking: which icons, not how many.

    The matcher sometimes hits the same weapon two or three times in one row
    (``UMP45+knock+UMP45``). As a tuple that differs from ``UMP45+knock`` and
    split one physical row into two lines."""
    return frozenset(icons)


@dataclass
class Line:
    """One kill-feed line followed across frames."""
    id: int
    icons: frozenset
    first_t: float
    last_t: float
    y: int
    h: int
    seen: int = 1
    futures: list = field(default_factory=list)       # Future[str] per OCR sample
    best_crop: np.ndarray = None
    confirmed: bool = False
    row: Row = None
    hist: list = field(default_factory=list)          # (t, row centre y) of every sighting
    etypes: dict = field(default_factory=dict)        # etype -> sightings that showed it
    weapons: dict = field(default_factory=dict)       # weapon -> sightings that named it
    ocr_t: float = None                               # time of the latest OCR sample
    masks: list = field(default_factory=list)         # (row_mask, crop) of early sightings, for short lines
    short: bool = False                               # confirmed via the short-line path (see LineTracker)
    folded: bool = False                              # absorbed into another line; never emit

    def sighted(self, t, r):
        self.hist.append((t, r.y + r.h / 2))     # centre: the panel's top edge jitters, its middle doesn't
        if len(self.masks) < 12:
            self.masks.append((r.row_mask, r.crop))
        self.etypes[r.etype] = self.etypes.get(r.etype, 0) + 1
        if r.weapon:
            self.weapons[r.weapon] = self.weapons.get(r.weapon, 0) + 1

    def absorb(self, other):
        """Take over another line's sightings: they were the same physical row."""
        self.hist = sorted(self.hist + other.hist)
        self.first_t, self.last_t = self.hist[0][0], max(self.last_t, other.last_t)
        self.seen += other.seen
        for k, n in other.etypes.items():
            self.etypes[k] = self.etypes.get(k, 0) + n
        for k, n in other.weapons.items():
            self.weapons[k] = self.weapons.get(k, 0) + n
        if not self.futures and other.futures:
            self.futures, self.best_crop = other.futures, other.best_crop

    @property
    def reads(self):
        """All completed full-row OCR strings."""
        return [f.result() for f in self.futures if f.done()]

    @property
    def reads_done(self):
        return all(f.done() for f in self.futures)

    @property
    def etype(self):
        """Majority over every sighting, not the latest one.

        An in-world nameplate sliding across a knock row hides its knock icon
        for a few frames; one such frame must not turn the knock into a kill.
        A tie goes to the more specific type (knock / eliminated_knocked)."""
        if not self.etypes:
            return self.row.etype
        return max(self.etypes, key=lambda e: (self.etypes[e], e != "kill"))

    @property
    def weapon(self):
        if not self.weapons:
            return None
        return max(self.weapons, key=self.weapons.get)

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
            k, ks, v, vs = row_names(raw_clean, roster)
            if k or v:
                candidates.append((k, ks, v, vs, raw_clean))

        raw_consensus = names.consensus(all_raws) if all_raws else ""

        if not candidates:
            return None, 0.0, None, 0.0, raw_consensus

        # Prefer readings where both names resolved
        both = [c for c in candidates if c[0] and c[2]]
        if both:
            votes = {}
            for k, ks, v, vs, _ in both:
                votes[(k, v)] = votes.get((k, v), 0) + min(ks, vs)
            k, v = max(votes, key=votes.get)
        else:
            # Only partial readings. Each one placed its name by position (see
            # row_names), so killer and victim can come from different readings.
            def pick(i):
                tally = {}
                for c in candidates:
                    if c[i]:
                        tally[c[i]] = tally.get(c[i], 0) + c[i + 1]
                return max(tally, key=tally.get) if tally else None
            k, v = pick(0), pick(2)
            if k and k == v:                        # can't be both: trust neither
                k = v = None
        k_sc = max((c[1] for c in candidates if k and c[0] == k), default=0.0)
        v_sc = max((c[3] for c in candidates if v and c[2] == v), default=0.0)
        return k, k_sc, v, v_sc, raw_consensus


class LineTracker:
    """Keeps each feed line's identity while it slides in and moves up the stack, so its names are read
    a few times (not every frame) and it becomes ONE event. Confirm after min_seen_s on screen.

    Sampling rate must not change the answer. Two things used to depend on it:
      - OCR samples were taken on sightings 2..4. At 4 fps that is 0.25-0.75 s
        into the row's life; at 24 fps it is the first ~0.1 s, while the row is
        still sliding in half-rendered. Samples are now spaced in TIME
        (ocr_spacing_s apart), so every rate reads the row at the same moments.
      - Identity required identical icons, so a frame where a nameplate hid the
        knock icon split one row into two lines -- at 24 fps often enough for
        the fragment to confirm as a phantom kill. See _same_row().
    """

    def __init__(self, min_seen_s=0.5, gap_s=1.0, ocr_samples=3, workers=2, ocr_spacing_s=0.25):
        self.min_seen_s, self.gap_s, self.ocr_samples = min_seen_s, gap_s, ocr_samples
        self.ocr_spacing_s = ocr_spacing_s
        self.lines, self._next = [], 1
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.waiting = []
        self.recent = []            # confirmed lines, kept while a fragment of them could still turn up
        self.short_min_seen = 2     # sightings a short line needs before it is even read
        self.merged = 0             # fragments folded into another line (reported by the engine)

    def update(self, t, rows):
        """Feed one frame's rows. Returns lines confirmed on this frame."""
        gone = [l for l in self.lines if t - l.last_t > self.gap_s]
        live = [l for l in self.lines if t - l.last_t <= self.gap_s]
        self.lines = live
        self.recent = [l for l in self.recent if t - l.last_t <= self.gap_s]
        used, newly = set(), []
        for r in sorted(rows, key=lambda r: r.y):
            key = icon_key(r.icons)
            best, best_d = None, 1e9
            for l in live:
                if l.id in used or l.icons != key:
                    continue
                dy = r.y - l.y
                same_slot = abs(dy) <= 4 and t - l.last_t <= 0.25
                moved_up = -60 <= dy <= 4 and abs(r.h - l.h) <= 6
                if same_slot or moved_up:
                    d = abs(dy) + abs(r.h - l.h)
                    if d < best_d:
                        best, best_d = l, d
            if best is None:
                best = Line(self._next, key, t, t, r.y, r.h, row=r)
                self._next += 1
                live.append(best)                   # live IS self.lines (appending to both listed it twice)
            else:
                best.last_t, best.y, best.h, best.row = t, r.y, r.h, r
                best.seen += 1
            best.sighted(t, r)
            used.add(best.id)
            # A6: OCR a few sightings, spaced in time (see class docstring). Spaced
            # from the previous sample, not from first_t, so a line that comes
            # back after a detection gap isn't sampled three frames in a row.
            if len(best.futures) < self.ocr_samples and \
                    t - (best.ocr_t or best.first_t) >= self.ocr_spacing_s - 1e-6:
                best.futures.append(self.pool.submit(names.ocr_mask, r.row_mask))
                best.best_crop, best.ocr_t = r.crop, t
            if not best.confirmed and best not in self.waiting \
                    and t - best.first_t >= self.min_seen_s - 1e-6 and best.seen >= 3:
                self.waiting.append(best)
        # Confirm once a line has its OCR samples (or has left the screen), and
        # WAIT for those reads rather than polling whether they are done yet.
        # Polling tied the moment of confirmation to wall-clock OCR speed; replay
        # runs far ahead of real time, so on a loaded machine a row could confirm
        # several video-seconds late and land in the wrong round. The wait costs
        # little: the reads were started 0.25-0.5 s of video earlier.
        need = self.ocr_samples                     # spaced in video time, so the same at every rate
        for l in list(self.waiting):
            if l not in self.waiting:               # absorbed earlier in this loop
                continue
            enough = len(l.futures) >= need or t - l.last_t > self.gap_s   # or the line is gone
            if l.futures and enough:
                for f in l.futures:
                    f.result()
                if self._fold_fragment(l):
                    continue
                l.confirmed = True
                newly.append(l)
                self.waiting.remove(l)
                self.recent.append(l)
        newly += self._short_lines(gone)
        return newly

    # -- short lines ---------------------------------------------------------
    def _short_lines(self, gone):
        """Lines that left the screen before min_seen_s.

        At a round end the camera cuts away, so the last rows of a round are
        often on screen for 0.07-0.3 s (measured on Video_Project_9). They never
        reach min_seen_s and used to vanish, leaving their eliminations as
        NO_FEED_ROW. Such a line is now read once it is gone and handed over
        marked `short`; the engine accepts it ONLY if it reads as two different
        roster names (see Engine._confirm). Nothing short is ever emitted on
        weaker evidence.
        """
        out = []
        for l in gone:
            if l.confirmed or l.folded or l in self.waiting or len(l.hist) < self.short_min_seen:
                continue
            if not l.icons:
                # Never matched an icon. Seen for real at 56.6 s: a nameplate
                # drifting below the feed, chained to one frame of a knock row
                # whose icons a second nameplate hid; that one frame read as
                # two names. Like A11, this path only adds rows nobody saw, so
                # asking it for icon evidence costs the main path nothing (A3).
                continue
            if self._fold_fragment(l):
                continue
            n = len(l.masks)
            pick = sorted({n // 4, n // 2, (3 * n) // 4}) if n > 3 else range(n)
            l.futures = [self.pool.submit(names.ocr_mask, l.masks[i][0]) for i in pick][:self.ocr_samples]
            for f in l.futures:
                f.result()
            l.best_crop = l.masks[pick[len(pick) // 2]][1] if n else None
            l.short = l.confirmed = True
            out.append(l)
        return out

    # -- fragments ---------------------------------------------------------
    @staticmethod
    def _same_row(a, b):
        """Were lines a and b the same physical feed row, split by icon flicker?

        Feed rows only ever move UP. So if a row sits in a slot at t1 and is
        still in that slot at t2, nothing else can have occupied the slot in
        between. Two lines whose sightings INTERLEAVE in the same slot, and that
        are never both detected in the same frame, are therefore one row.

        Slots are ~45 px apart; "same slot" is row centres within 8 px.

        Deliberately narrow: lines that merely follow each other in a slot
        (old row moved up undetected, new row arrived) are NOT merged -- that
        is how two real events in a row look.
        """
        ta = {t for t, _ in a.hist}
        if any(t in ta for t, _ in b.hist):
            return False                            # seen together = two rows
        for frag, host in ((a, b), (b, a)):
            hits = 0
            for t, y in frag.hist:
                before = [hy for ht, hy in host.hist if ht < t]
                after = [hy for ht, hy in host.hist if ht > t]
                if before and after and abs(before[-1] - y) <= 8 and abs(after[0] - y) <= 8:
                    hits += 1
            if hits and hits * 2 >= len(frag.hist):  # most of frag sits inside host's stay in that slot
                return True
        return False

    def _fold_fragment(self, line):
        """Before confirming `line`, fold together every line that is the same row.

        The one already confirmed, else the one seen most, keeps the identity.
        Returns True if `line` was absorbed (and must not be emitted)."""
        while True:
            other = next((o for o in self.recent + self.lines
                          if o is not line and self._same_row(line, o)), None)
            if other is None:
                return False
            if other.confirmed or other.seen >= line.seen:
                host, frag = other, line
            else:
                host, frag = line, other
            host.absorb(frag)
            frag.folded = True
            self.merged += 1
            for lst in (self.lines, self.waiting, self.recent):
                lst[:] = [x for x in lst if x is not frag]
            if frag is line:
                return True

    def flush(self):
        """End of source: wait for outstanding reads and return lines that qualified but weren't confirmed."""
        out = []
        for l in list(self.waiting):
            if l not in self.waiting:
                continue
            for f in l.futures:
                f.result()
            if self._fold_fragment(l):
                continue
            l.confirmed = True
            self.recent.append(l)
            out.append(l)
        self.waiting = []
        out += self._short_lines(list(self.lines))
        return out
