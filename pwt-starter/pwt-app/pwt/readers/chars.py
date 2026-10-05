"""Character templates for player names (replaces Tesseract).

Same idea as digits.py but for A-Z, a-z, 0-9 and common symbols.
Each character gets its own template PNGs in a folder:

    chars_feed/         kill-feed names (from white_mask, ~12 px tall)
    chars_board/        scoreboard names (from Otsu binarisation, larger)

Template filenames use ordinals for Windows compatibility (NTFS is
case-insensitive, so A_0.png and a_0.png would collide):

    c65_0.png   -> 'A'  (ord 65)
    c97_0.png   -> 'a'  (ord 97)
    c48_0.png   -> '0'  (ord 48)
"""
import glob, os
from collections import Counter, defaultdict
import cv2, numpy as np

SIZE = (24, 36)          # normalisation target (w, h) — larger than digits to preserve
                         # detail in the tiny (~6 px wide) feed characters
_MIN_TPL_W = 3           # reject harvested templates narrower than this (stem fragments)

# Shape-penalty weights: [aspect_ratio, top_weight, left_weight, density].
# Tuned so the penalty is ~0.05-0.08 for structurally different chars (enough
# to flip a 0.02 NCC tie) but <0.02 for same-char variants.
_SHAPE_W = np.array([0.20, 0.10, 0.10, 0.08], dtype=np.float32)


def _norm(g):
    # Use INTER_NEAREST for very small glyphs to avoid blurring away edges,
    # INTER_AREA for larger ones to antialias properly.
    interp = cv2.INTER_NEAREST if min(g.shape[:2]) < 10 else cv2.INTER_AREA
    v = cv2.resize(g, SIZE, interpolation=interp).astype(np.float32).ravel()
    return (v - v.mean()) / (v.std() + 1e-6)


def _shape(g):
    """Compact shape descriptor: [aspect_ratio, top_weight, left_weight, density]."""
    h, w = g.shape[:2]
    bw = (g > 127).astype(np.float32) if g.max() > 1 else g.astype(np.float32)
    total = bw.sum() + 1e-6
    mh, mw = max(h // 2, 1), max(w // 2, 1)
    return np.array([
        w / max(h, 1),               # aspect ratio
        bw[:mh, :].sum() / total,     # fraction of mass in top half
        bw[:, :mw].sum() / total,     # fraction of mass in left half
        total / max(h * w, 1),        # pixel density
    ], dtype=np.float32)


def _label(ch):
    """Character -> filesystem-safe label:  'A' -> 'c65'."""
    return f"c{ord(ch)}"


def _char(label):
    """Filesystem label -> character:  'c65' -> 'A'."""
    return chr(int(label[1:]))


class CharReader:
    def __init__(self, folder, min_score=0.55, min_h=6):
        self.folder, self.min_score, self.min_h = str(folder), min_score, min_h
        self.reload()

    def reload(self):
        # Pass 1: load all templates, filtering only stem fragments.
        raw = []
        for p in sorted(glob.glob(os.path.join(self.folder, "c*_*.png"))):
            base = os.path.basename(p)
            lab = base.split("_")[0]                         # e.g. 'c65'
            try:
                ch = _char(lab)
            except (ValueError, OverflowError):
                continue
            img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
            if img is None or img.shape[1] < _MIN_TPL_W:
                continue
            raw.append((ch, _norm(img), _shape(img), img.shape[0]))

        # Pass 2: height pruning — the harvester sometimes labels a glyph
        # as the wrong character when names share the same length.
        # Correct templates of a character cluster at one height; outliers
        # from a different height band are almost certainly mislabelled.
        # Keep only templates within ±3 px of the character's modal height.
        by_char = defaultdict(list)
        for i, (ch, *_) in enumerate(raw):
            by_char[ch].append(i)
        keep = set()
        for ch, idxs in by_char.items():
            heights = [raw[i][3] for i in idxs]
            binned = [h // 2 * 2 for h in heights]
            mode_bin = Counter(binned).most_common(1)[0][0]
            for i in idxs:
                if abs(raw[i][3] - mode_bin) <= 3:
                    keep.add(i)
        pruned = [raw[i] for i in sorted(keep)]

        # Pass 3: within-class NCC pruning — remove templates that are
        # outliers even within the surviving height group.
        by_char2 = defaultdict(list)
        for i, (ch, *_) in enumerate(pruned):
            by_char2[ch].append(i)
        keep2 = set()
        for ch, idxs in by_char2.items():
            if len(idxs) <= 2:
                keep2.update(idxs)
                continue
            scores = []
            for i in idxs:
                siblings = [j for j in idxs if j != i]
                avg = float(np.mean([float((pruned[i][1] * pruned[j][1]).mean())
                                     for j in siblings]))
                scores.append((avg, i))
            scores.sort()
            thresh = min(scores[len(scores) // 2][0], 0.2)
            good = [i for _, i in scores if _ >= thresh]
            keep2.update(good if len(good) >= 2 else [i for _, i in scores])

        self.templates = [pruned[i] for i in sorted(keep2)]

    @property
    def ready(self):
        return len(self.templates) >= 26                     # at least the alphabet

    # ---- glyph segmentation ----

    def glyphs(self, mask01):
        """Connected components from a 0/1 binary mask, sorted left-to-right.

        Merges dots above stems (for 'i', 'j', '!') and filters icon remnants.
        Returns list of glyph images (uint8 0/255).
        """
        m = (mask01 * 255).astype(np.uint8) if mask01.max() <= 1 else mask01
        n, labels, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        if n <= 1:
            return []

        comps = []
        for i in range(1, n):
            x, y, w, h, a = stats[i]
            comps.append(dict(x=int(x), y=int(y), w=int(w), h=int(h),
                              area=int(a), idx=i, merged=False))

        # merge dots: small component directly above a taller one
        comps.sort(key=lambda c: c["y"])                     # top to bottom
        for s in comps:
            if s["h"] >= 6 or s["area"] >= 15 or s["merged"]:
                continue
            sx_mid = s["x"] + s["w"] / 2
            for t in comps:
                if t is s or t["h"] < 8 or t["merged"]:
                    continue
                tx_mid = t["x"] + t["w"] / 2
                if (abs(sx_mid - tx_mid) < 4
                        and s["y"] + s["h"] <= t["y"] + 3):     # dot is above stem
                    # expand t to include s
                    new_y = min(s["y"], t["y"])
                    new_x = min(s["x"], t["x"])
                    new_r = max(s["x"] + s["w"], t["x"] + t["w"])
                    new_b = max(s["y"] + s["h"], t["y"] + t["h"])
                    t.update(x=new_x, y=new_y, w=new_r - new_x, h=new_b - new_y)
                    s["merged"] = True
                    break

        # filter: min size and max size (reject icon leaks)
        keep = [c for c in comps if not c["merged"]
                and c["h"] >= self.min_h and c["area"] >= 4]
        if not keep:
            return []

        median_h = float(np.median([c["h"] for c in keep]))
        keep = [c for c in keep
                if c["w"] <= max(c["h"] * 1.8, 14)              # reject wide icon fragments
                and c["h"] <= median_h * 2.2]                    # reject tall outliers

        keep.sort(key=lambda c: c["x"])
        return [m[c["y"]:c["y"] + c["h"], c["x"]:c["x"] + c["w"]] for c in keep]

    # ---- classification ----

    def classify(self, glyph):
        """(character, score) for a single glyph image.

        Uses pixel NCC as the primary metric, with a shape penalty and
        a height penalty.  The height penalty is the strongest signal:
        uppercase letters are ~13 px tall in the feed font while
        lowercase body letters are ~8 px, so a large height mismatch
        reliably indicates a wrong candidate.
        """
        v = _norm(glyph)
        sv = _shape(glyph)
        gh = glyph.shape[0]
        # Per-character best adjusted score
        char_best = {}
        for ch, t, ts, th in self.templates:
            pixel_s = float((t * v).mean())
            shape_pen = float(np.abs(sv - ts) @ _SHAPE_W)
            # Height penalty: 0 for <=2 px diff, then 0.04 per px.
            # 5 px diff (upper vs lower) → 0.20 penalty, enough to
            # overwhelm a spurious NCC advantage.
            hdiff = abs(gh - th)
            height_pen = 0.0 if hdiff <= 2 else 0.04 * hdiff
            adj = pixel_s - shape_pen - height_pen
            if ch not in char_best or adj > char_best[ch]:
                char_best[ch] = adj
        if not char_best:
            return "?", -1.0
        best_c = max(char_best, key=char_best.get)
        return best_c, char_best[best_c]

    def read(self, mask01):
        """Read a player name from a binary mask.  Returns the string."""
        gs = self.glyphs(mask01)
        if not gs or not self.templates:
            return ""
        parts = []
        for g in gs:
            ch, sc = self.classify(g)
            parts.append(ch if sc >= self.min_score else "?")
        return "".join(parts)

    # ---- harvesting ----

    def harvest(self, mask01, text, max_per_char=6):
        """Save character templates from a mask whose text is known.

        Returns the number of glyphs saved, or 0 if the glyph count doesn't
        match the text length (alignment would be wrong).
        """
        gs = self.glyphs(mask01)
        if len(gs) != len(text):
            return 0
        os.makedirs(self.folder, exist_ok=True)
        saved = 0
        for g, ch in zip(gs, text):
            lab = _label(ch)
            existing = len(glob.glob(os.path.join(self.folder, f"{lab}_*.png")))
            if existing >= max_per_char:
                continue                                         # enough variants already
            cv2.imwrite(os.path.join(self.folder, f"{lab}_{existing}.png"), g)
            saved += 1
        if saved:
            self.reload()
        return saved
