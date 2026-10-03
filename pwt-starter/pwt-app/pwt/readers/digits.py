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
        g = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2GRAY) if cell_bgr.ndim == 3 else cell_bgr
        _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)       # white glyphs
        n, _, stats, _ = cv2.connectedComponentsWithStats(b, 8)
        out = [(x, b[y:y + h, x:x + w]) for x, y, w, h, a in stats[1:]
               if h >= self.min_h and a >= 15 and w <= h * 1.2]
        return [g for _, g in sorted(out, key=lambda t: t[0])]

    def classify(self, glyph):
        v = _norm(glyph)
        best = max(((float((t * v).mean()), d) for d, t in self.templates), default=(-1.0, None))
        return best[1], best[0]

    def read(self, cell_bgr):
        """(int or None, weakest glyph score)."""
        gs = self.glyphs(cell_bgr)
        if not gs or not self.templates: return None, 0.0
        ds, scores = zip(*(self.classify(g) for g in gs))
        if min(scores) < self.min_score: return None, round(min(scores), 2)
        return int("".join(ds)), round(min(scores), 2)

    def harvest(self, cell_bgr, text):
        """Save the glyphs of a cell whose true value is known (e.g. fixed in the review screen)."""
        gs = self.glyphs(cell_bgr)
        if len(gs) != len(str(text)): return 0
        os.makedirs(self.folder, exist_ok=True)
        for g, ch in zip(gs, str(text)):
            k = len(glob.glob(os.path.join(self.folder, f"{ch}_*.png")))
            cv2.imwrite(os.path.join(self.folder, f"{ch}_{k}.png"), g)
        self.reload()
        return len(gs)
