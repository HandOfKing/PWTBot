"""Layout profiles: every HUD coordinate lives in a JSON profile, never in code (CLAUDE.md)."""
import json
from pathlib import Path

BUILTIN = Path(__file__).parent
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


class Profile(dict):
    """dict with attribute access; `templates` is the folder icon/digit/header images load from."""
    __getattr__ = dict.__getitem__

    @property
    def templates(self) -> Path:
        return Path(self.get("templates_dir") or TEMPLATES)

    def helmets(self, team_size):
        h = self["banner"]["helmets"]
        return h.get(str(team_size)) or h[sorted(h, key=lambda k: abs(int(k) - team_size))[0]]


def load(name_or_path="gameloop-windowed-1080p") -> Profile:
    """A built-in profile name, or a path to a JSON file (e.g. one saved by the calibration tool)."""
    p = Path(name_or_path)
    if not p.suffix:
        user = None
        try:
            from ..db import data_dir
            user = data_dir() / "profiles" / f"{name_or_path}.json"
        except Exception:
            pass
        p = user if user and user.exists() else BUILTIN / f"{name_or_path}.json"
    return Profile(json.loads(p.read_text(encoding="utf-8")))
