"""Player names: character templates (no external dependencies), then fuzzy roster matching (brief §5.2).

Feed names are read by CharReader from binary masks.  Scoreboard names use CharReader on
Otsu-binarised crops; Tesseract is an optional fallback if installed."""
import os, shutil, subprocess, difflib, sys
from pathlib import Path
import cv2, numpy as np
from .chars import CharReader

_TEMPLATES = Path(__file__).resolve().parents[1] / "templates"

# ---- lazy singletons ----

_feed_reader = None
_board_reader = None


def _get_feed_reader():
    global _feed_reader
    if _feed_reader is None:
        _feed_reader = CharReader(_TEMPLATES / "chars_feed")
    return _feed_reader


def _get_board_reader():
    global _board_reader
    if _board_reader is None:
        _board_reader = CharReader(_TEMPLATES / "chars_board", min_score=0.50, min_h=8)
    return _board_reader


def _tesseract_cmd():
    if os.environ.get("PWT_TESSERACT"): return os.environ["PWT_TESSERACT"]
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    for p in (base / "vendor" / "tesseract" / "tesseract.exe", base / "vendor" / "tesseract" / "tesseract"):
        if p.exists(): return str(p)
    return shutil.which("tesseract")                         # None when not installed


_CMD = _tesseract_cmd()


def ocr_mask(mask01):
    """Text from a 0/1 mask of white text (kill-feed names).

    Uses CharReader templates (no external dependency).  Falls back to Tesseract
    if templates aren't ready yet and Tesseract is installed.
    """
    reader = _get_feed_reader()
    if reader.ready:
        return reader.read(mask01)
    if _CMD:
        return _tess_mask(mask01)
    return ""


def _tess_mask(mask01):
    img = 255 - cv2.resize((mask01 * 255).astype(np.uint8), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    return _run(cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255))


def ocr_bgr(crop):
    """Several readings of light text on a dark background (scoreboard names).

    Primary: CharReader on Otsu-binarised variants.
    Fallback: Tesseract on the same variants (if installed).
    """
    g0 = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    reader = _get_board_reader()
    out = []

    for sc in (4, 5):
        g = cv2.resize(g0, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
        _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        bordered = cv2.copyMakeBorder(b, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=255)
        if reader.ready:
            mask01 = (bordered < 128).astype(np.uint8)
            r = reader.read(mask01)
        elif _CMD:
            r = _run(bordered)
        else:
            r = ""
        if r: out.append(r)

    g = 255 - cv2.resize(g0, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    bordered = cv2.copyMakeBorder(g, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=255)
    if reader.ready:
        mask01 = (bordered < 128).astype(np.uint8)
        r = reader.read(mask01)
    elif _CMD:
        r = _run(bordered)
    else:
        r = ""
    if r: out.append(r)

    return out


def _run(img):
    if not _CMD:
        return ""
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
