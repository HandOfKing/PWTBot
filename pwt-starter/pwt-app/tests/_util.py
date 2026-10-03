"""Shared test helpers. Tests run with pytest, or without it: python tests/run_all.py"""
import shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"
CLIP = ROOT / "clips" / "Video_Project_7.mp4"


def has_tesseract():
    from pwt.readers.names import _CMD
    return shutil.which(_CMD) is not None or Path(_CMD).exists()


def fresh_db():
    from pwt import db
    d = Path(tempfile.mkdtemp())
    return db.connect(d / "pwt.db"), d


class Skip(Exception):
    """Raised to skip a test when an optional dependency (tesseract, the test clip) is missing."""


def skip(msg):
    try:
        import pytest
        pytest.skip(msg)
    except ImportError:
        raise Skip(msg)
