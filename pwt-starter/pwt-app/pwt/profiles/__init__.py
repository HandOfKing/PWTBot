"""Layout profiles: every HUD coordinate lives in a JSON profile, never in code (CLAUDE.md)."""
import json, logging
from pathlib import Path

BUILTIN = Path(__file__).parent
DEFAULT = "gameloop-spectator-6v6-1080p"     # the one layout: first-person spectator, 6v6, GameLoop 1080p
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
log = logging.getLogger(__name__)


class Profile(dict):
    """dict with attribute access; `templates` is the folder icon/digit/header images load from."""
    __getattr__ = dict.__getitem__

    @property
    def templates(self) -> Path:
        return Path(self.get("templates_dir") or TEMPLATES)

    def helmets(self, team_size):
        h = self["banner"]["helmets"]
        pos = h.get(str(team_size))
        if pos is None:
            avail = ", ".join(sorted(h))
            raise KeyError(
                f"Profile {self.get('name', '?')!r} has no helmet_positions for "
                f"team_size={team_size} (available: {avail}). "
                f"Measure the positions and add them to the profile JSON."
            )
        return pos


def _scale_value(v, factor):
    """Recursively scale pixel values by *factor*."""
    if isinstance(v, int):
        return round(v * factor)
    if isinstance(v, float):
        return v  # thresholds, seconds, etc. — don't scale
    if isinstance(v, list):
        return [_scale_value(x, factor) for x in v]
    if isinstance(v, dict):
        return {k: _scale_value(x, factor) for k, x in v.items()}
    return v


# Keys whose values are pixel coordinates / sizes and should be scaled.
_PIXEL_KEYS = {
    "box", "padding_px", "row_h_min", "row_h_max", "bridge",
    "capture_region", "game_area", "remaining_box", "creation_code_box",
    "blue_score_box", "red_score_box",
    "header_band", "player_col", "team_col", "table_y",
}


def _scale_profile(prof, frame_h):
    """Scale every pixel value when the video resolution differs from the profile."""
    res = prof.get("resolution")
    if res is None:
        return prof
    profile_h = res[1]
    if frame_h == profile_h:
        return prof
    factor = frame_h / profile_h
    log.info("Scaling profile %r from %dp to %dp (factor %.3f). "
             "Run calibrate to confirm.", prof.get("name"), profile_h, frame_h, factor)

    def _walk(d):
        out = {}
        for k, v in d.items():
            if k in _PIXEL_KEYS:
                out[k] = _scale_value(v, factor)
            elif isinstance(v, dict):
                out[k] = _walk(v)
            else:
                out[k] = v
        return out

    scaled = _walk(prof)
    scaled["resolution"] = [round(res[0] * factor), frame_h]
    return scaled


def load(name_or_path=DEFAULT, frame_size=None) -> Profile:
    """A built-in profile name, or a path to a JSON file.

    *frame_size* is (width, height) of the video being analysed.
    If it differs from the profile's ``resolution``, every pixel value is
    scaled by ``actual_height / profile_height`` and a log message is emitted.
    """
    p = Path(name_or_path)
    if not p.suffix:
        user = None
        try:
            from ..db import data_dir
            user = data_dir() / "profiles" / f"{name_or_path}.json"
        except Exception:
            pass
        p = user if user and user.exists() else BUILTIN / f"{name_or_path}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    if frame_size is not None:
        data = _scale_profile(data, frame_size[1])
    return Profile(data)
