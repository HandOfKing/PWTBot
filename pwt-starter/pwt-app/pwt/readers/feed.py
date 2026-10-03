"""Kill feed: find rows, classify icons, read names, and TRACK each line while it is on screen (brief §5.2, §4.3).

Row grammar:  killer · weapon · knock-icon · victim   -> knock
              killer · weapon · victim                -> kill
              killer · tombstone · victim             -> eliminated_knocked
New rows enter the bottom slot and older rows shift up. A line stays about 3.5 s.
"""
import glob, os
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


@dataclass
class Row:
    y: int                      # absolute y of the row's top
    icons: tuple                # e.g. ('weapon_UMP45', 'icon_knock')
    k_span: tuple               # killer text x-range (crop coords)
    v_span: tuple               # victim text x-range
    k_mask: np.ndarray
    v_mask: np.ndarray
    crop: np.ndarray            # colour crop of the whole row, for evidence

    @property
    def etype(self):
        if "icon_knock" in self.icons: return "knock"
        if "icon_tombstone" in self.icons: return "eliminated_knocked"
        return "kill"

    @property
    def weapon(self):
        return next((i[7:] for i in self.icons if i.startswith("weapon_")), None)


class FeedReader:
    def __init__(self, profile):
        f = profile["feed"]
        self.box = f["box"]; self.left = f["row_left_x"]; self.thresh = f["icon_thresh"]
        self.icons = load_icons(profile.templates / "icons")

    def rows(self, frame):
        x0, y0, x1, y1 = self.box
        crop = frame[y0:y1, x0:x1]
        m = white_mask(crop)
        out = []
        for ry0, ry1 in self._row_bands(m):
            col = m[ry0:ry1].sum(0); col[:12] = 0
            xs = np.where(col > 0)[0]
            if not len(xs) or not (self.left[0] <= xs[0] + x0 <= self.left[1]):
                continue                                         # not left-aligned: in-world name tag etc.
            icons = self._icons(m, ry0, ry1)
            if not icons: continue                               # no icon = not a feed row
            ks = self._span(m, ry0, ry1, 12, icons[0][1] + 1, "left")
            vs = self._span(m, ry0, ry1, icons[-1][2] - 1, m.shape[1], "right")
            if not ks or not vs or ks[1] - ks[0] < 12 or vs[1] - vs[0] < 12: continue
            a, b = max(0, ry0 - 2), ry1 + 2
            out.append(Row(y=ry0 + y0, icons=tuple(c[3] for c in icons), k_span=ks, v_span=vs,
                           k_mask=m[a:b, ks[0]:ks[1]], v_mask=m[a:b, vs[0]:vs[1]],
                           crop=crop[max(0, ry0 - 8):ry1 + 8, :max(vs[1] + 10, 1)].copy()))
        return out

    @staticmethod
    def _row_bands(m):
        prof = m[:, 14:440].sum(1)                               # skip the window edge
        rows, y, H = [], 0, len(prof)
        while y < H:
            if prof[y] >= 3:
                s = y
                while y < H and prof[y] >= 2: y += 1
                if 9 <= y - s <= 26: rows.append((s, y))
            y += 1
        return rows

    def _icons(self, m, y0, y1):
        band = m[max(0, y0 - 6):y1 + 6].astype(np.float32)
        cands = []
        for n, t in self.icons.items():
            if t.shape[0] > band.shape[0] or t.shape[1] > band.shape[1]: continue
            r = cv2.matchTemplate(band, t, cv2.TM_CCOEFF_NORMED).max(0)
            for x in np.where(r >= self.thresh)[0]:
                if r[x] == r[max(0, x - 4):x + 5].max():
                    cands.append((float(r[x]), int(x), int(x + t.shape[1]), n))
        keep = []
        for c in sorted(cands, reverse=True):
            if all(c[2] <= k[1] + 3 or c[1] >= k[2] - 3 for k in keep): keep.append(c)
        return sorted(keep, key=lambda c: c[1])

    @staticmethod
    def _span(m, y0, y1, a, b, direction):
        xs = np.where(m[y0:y1, a:b].sum(0) > 0)[0]
        if not len(xs): return None
        if direction == "right":                                 # victim: stop at the first big gap
            end = xs[0]
            for x in xs[1:]:
                if x - end > 14: break
                end = x
            return a + xs[0], a + end + 1
        return a + xs[0], a + xs[-1] + 1


@dataclass
class Line:
    """One kill-feed line followed across frames."""
    id: int
    icons: tuple
    first_t: float
    last_t: float
    y: int
    kw: int
    vw: int
    seen: int = 1
    futures: list = field(default_factory=list)       # (killer_future, victim_future) per OCR sample
    best_crop: np.ndarray = None
    confirmed: bool = False
    row: Row = None

    @property
    def k_reads(self): return [k.result() for k, v in self.futures if k.done()]

    @property
    def v_reads(self): return [v.result() for k, v in self.futures if v.done()]

    @property
    def reads_done(self): return all(k.done() and v.done() for k, v in self.futures)

    @property
    def etype(self): return self.row.etype

    @property
    def weapon(self): return self.row.weapon


class LineTracker:
    """Keeps each feed line's identity while it slides in and moves up the stack, so its names are read
    a few times (not every frame) and it becomes ONE event. Confirm after min_seen_s on screen."""

    def __init__(self, min_seen_s=0.5, gap_s=1.0, ocr_samples=3, workers=2):
        self.min_seen_s, self.gap_s, self.ocr_samples = min_seen_s, gap_s, ocr_samples
        self.lines, self._next = [], 1
        self.pool = ThreadPoolExecutor(max_workers=workers)       # tesseract runs off the analyser thread
        self.waiting = []                                         # on screen long enough, reads still running

    def update(self, t, rows):
        """Feed one frame's rows. Returns lines confirmed on this frame (seen long enough AND names read).
        Never blocks: a line whose OCR is still running is confirmed on a later frame."""
        live = [l for l in self.lines if t - l.last_t <= self.gap_s]
        self.lines = live
        used, newly = set(), []
        for r in sorted(rows, key=lambda r: r.y):
            kw, vw = r.k_span[1] - r.k_span[0], r.v_span[1] - r.v_span[0]
            best, best_d = None, 1e9
            for l in live:
                if l.id in used or l.icons != r.icons: continue
                dy = r.y - l.y
                same_slot = abs(dy) <= 4 and t - l.last_t <= 0.25           # sliding in: width may change
                moved_up = -60 <= dy <= 4 and abs(kw - l.kw) <= 6 and abs(vw - l.vw) <= 6
                if same_slot or moved_up:
                    d = abs(dy) + abs(kw - l.kw) + abs(vw - l.vw)
                    if d < best_d: best, best_d = l, d
            if best is None:
                best = Line(self._next, r.icons, t, t, r.y, kw, vw, row=r); self._next += 1
                self.lines.append(best); live.append(best)
            else:
                best.last_t, best.y, best.kw, best.vw, best.row = t, r.y, kw, vw, r
                best.seen += 1
            used.add(best.id)
            if len(best.futures) < self.ocr_samples and best.seen >= 2:   # skip the slide-in frame
                best.futures.append((self.pool.submit(names.ocr_mask, r.k_mask), self.pool.submit(names.ocr_mask, r.v_mask)))
                best.best_crop = r.crop
            if not best.confirmed and best not in self.waiting and t - best.first_t >= self.min_seen_s - 1e-6 \
                    and best.seen >= 3:
                self.waiting.append(best)
        for l in list(self.waiting):
            if l.futures and l.reads_done:
                l.confirmed = True; newly.append(l); self.waiting.remove(l)
        return newly

    def flush(self):
        """End of source: wait for outstanding reads and return lines that qualified but weren't confirmed."""
        out = []
        for l in self.waiting:
            for k, v in l.futures: k.result(); v.result()
            l.confirmed = True; out.append(l)
        self.waiting = []
        return out
