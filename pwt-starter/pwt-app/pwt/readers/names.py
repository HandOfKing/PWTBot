"""Player names: tesseract on a clean binary crop, then fuzzy roster matching (brief §5.2).
Raw OCR of the stylised names is rough ('TheWalverine', 'Makpets6d'); never trust it unmatched."""
import os, shutil, subprocess, difflib, sys
from pathlib import Path
import cv2, numpy as np


def tesseract_cmd():
    """PWT_TESSERACT env var, a bundled vendor/tesseract next to the exe, or tesseract on PATH."""
    if os.environ.get("PWT_TESSERACT"): return os.environ["PWT_TESSERACT"]
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    for p in (base / "vendor" / "tesseract" / "tesseract.exe", base / "vendor" / "tesseract" / "tesseract"):
        if p.exists(): return str(p)
    return shutil.which("tesseract") or "tesseract"


_CMD = tesseract_cmd()


def ocr_mask(mask01):
    """Text from a 0/1 mask of white text (as produced by readers.mask.white_mask)."""
    img = 255 - cv2.resize((mask01 * 255).astype(np.uint8), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    return _run(cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255))


def ocr_bgr(crop):
    """Several readings of light text on a dark background (scoreboard names), one per image variant.
    Tesseract is erratic on this font and the best scale changes frame to frame; voting over Otsu x4, Otsu x5
    and plain grey x4 read 20/20 test-clip names correctly where any single variant read 5-15/20."""
    g0 = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    out = []
    for sc in (4, 5):
        g = cv2.resize(g0, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
        _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        out.append(_run(cv2.copyMakeBorder(b, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=255)))
    g = 255 - cv2.resize(g0, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    out.append(_run(cv2.copyMakeBorder(g, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=255)))
    return [o for o in out if o]


def _run(img):
    try:
        r = subprocess.run([_CMD, "stdin", "stdout", "--psm", "7"], input=cv2.imencode(".png", img)[1].tobytes(),
                           capture_output=True, timeout=10)
        return r.stdout.decode(errors="ignore").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def norm(s):
    return "".join(ch for ch in (s or "").lower().replace("ø", "o").replace("0", "o") if ch.isalnum())


def similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def match(raw, roster):
    """Best roster name for an OCR string -> (name or None, score 0..1)."""
    n = norm(raw)
    if not n or not roster: return None, 0.0
    sc, name = max((difflib.SequenceMatcher(None, n, norm(r)).ratio(), r) for r in roster)
    return name, round(sc, 2)


def consensus(readings):
    """Best single spelling from several noisy readings of the same name, for names not on any roster yet.
    A spelling read identically at least twice and by >= 40% of readings wins; otherwise the reading most similar
    to all the others (medoid). Returns '' if nothing was read."""
    rs = ["".join(ch for ch in r.strip() if ch.isalnum() or ch in "_-.") for r in readings if r and r.strip()]
    rs = [r for r in rs if r]
    if not rs: return ""
    top = max(set(rs), key=rs.count)
    if rs.count(top) >= 2 and rs.count(top) / len(rs) >= 0.4: return top
    return max(rs, key=lambda r: sum(similar(norm(r), norm(o)) for o in rs))


def agreement(readings, spelling):
    """Share of readings that match the chosen spelling exactly (for flagging new names)."""
    rs = ["".join(ch for ch in r.strip() if ch.isalnum() or ch in "_-.") for r in readings if r and r.strip()]
    return round(rs.count(spelling) / len(rs), 2) if rs else 0.0
