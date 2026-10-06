"""Numbers by glyph templates (brief §5.4). The HUD font is condensed and tesseract misreads it
('52' -> '2'), so numbers are NEVER read with OCR. Unknown glyph -> None -> the caller flags it.

Each font gets its own folder of glyph PNGs named <digit>_<n>.png:
  digits_board/      scoreboard cells and Team column
  digits_remaining/  the Remaining counter
  digits_banner/     the round banner score
"""
import glob, os, cv2, numpy as np

SIZE = (16, 24)


def _norm(g):
    v = cv2.resize(g, SIZE, interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
    return (v - v.mean()) / (v.std() + 1e-6)


class DigitReader:
    def __init__(self, folder, min_score=0.80, min_h=10):
        self.folder, self.min_score, self.min_h = str(folder), min_score, min_h
        self.reload()

    def reload(self):
        self.templates = []
        for p in sorted(glob.glob(os.path.join(self.folder, "*.png"))):
            self.templates.append((os.path.basename(p).split("_")[0], _norm(cv2.imread(p, cv2.IMREAD_GRAYSCALE))))

    def glyphs(self, cell_bgr):
        """Glyph images left to right, or None if the cell holds ink that cannot be split into glyphs.

        Some digits touch in this font ("3649" renders as "3" + one blob for "649"). Such a blob
        used to be dropped as too wide, so the cell read "3": a WRONG number. A blob is now split
        at its thinnest columns into as many glyphs as its width implies; if that cannot be done,
        the whole cell is unreadable (None), never a shorter number.
        """
        g = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2GRAY) if cell_bgr.ndim == 3 else cell_bgr
        _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)       # white glyphs
        n, _, stats, _ = cv2.connectedComponentsWithStats(b, 8)
        comps = sorted((x, y, w, h) for x, y, w, h, a in stats[1:] if h >= self.min_h and a >= 15)
        # a digit in this condensed font is ~0.5x its height; two touching ones are ~1.05x, which a
        # height-based limit let through as ONE glyph (read as blank). Measure against the width
        # of the cell's own single digits instead.
        single = [w for x, y, w, h in comps if 0.35 * h <= w <= 0.75 * h]          # one digit, not "1"
        out = []
        for x, y, w, h in comps:
            box = b[y:y + h, x:x + w]
            gw = float(np.median(single)) if single else 0.5 * h
            if w < 1.6 * gw:
                out.append(box); continue
            k = int(round((w + 1) / (gw + 1)))
            if k < 2 or k > 6:
                return None
            col = box.sum(0).astype(np.float32)
            cuts, win = [0], max(2, int(gw / 3))
            for i in range(1, k):
                c = int(round(i * w / k))
                lo, hi = max(cuts[-1] + 2, c - win), min(w - 2, c + win)
                if hi <= lo: return None
                cuts.append(lo + int(np.argmin(col[lo:hi + 1])))
            cuts.append(w)
            for a0, a1 in zip(cuts, cuts[1:]):
                piece = box[:, a0:a1]
                ink = np.where(piece.sum(0) > 0)[0]
                if len(ink) < 2: return None
                out.append(piece[:, ink[0]:ink[-1] + 1])
        return out

    def classify(self, glyph):
        v = _norm(glyph)
        best = max(((float((t * v).mean()), d) for d, t in self.templates), default=(-1.0, None))
        return best[1], best[0]

    def read(self, cell_bgr):
        """(int or None, weakest glyph score)."""
        gs = self.glyphs(cell_bgr)
        if not gs or not self.templates: return None, 0.0                  # None: unsplittable ink
        ds, scores = zip(*(self.classify(g) for g in gs))
        if min(scores) < self.min_score: return None, round(min(scores), 2)
        return int("".join(ds)), round(min(scores), 2)

    def harvest(self, cell_bgr, text):
        """Save the glyphs of a cell whose true value is known (e.g. fixed in the review screen)."""
        gs = self.glyphs(cell_bgr)
        if not gs or len(gs) != len(str(text)): return 0
        os.makedirs(self.folder, exist_ok=True)
        for g, ch in zip(gs, str(text)):
            k = len(glob.glob(os.path.join(self.folder, f"{ch}_*.png")))
            cv2.imwrite(os.path.join(self.folder, f"{ch}_{k}.png"), g)
        self.reload()
        return len(gs)
