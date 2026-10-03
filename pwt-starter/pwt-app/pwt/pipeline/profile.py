"""Layout profile: all HUD coordinates for one recording setup.

Profiles are JSON files stored in  <repo>/profiles/<name>.json.
Pass a name (no extension) or a full path to LayoutProfile.load().
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# profiles/ lives two levels above this file (pwt/pipeline/ -> pwt/ -> app root -> profiles/)
_PROFILES_DIR = Path(__file__).parent.parent.parent / "profiles"


@dataclass
class LayoutProfile:
    # --- identity ---
    name: str
    resolution: tuple[int, int]                 # (width, height) of the recording

    # --- kill-feed crop (full-frame pixel coords) ---
    feed_box: tuple[int, int, int, int]          # (x0, y0, x1, y1)
    # rows are filtered to those whose leftmost content falls in this x-range
    # (crop-relative, i.e. feed_box[0] is x=0)
    row_left_min: int
    row_left_max: int

    # --- HUD counters ---
    remaining_box: tuple[int, int, int, int]     # digit region (x0,y0,x1,y1)

    # --- banner score (for banner_visible check and round winner) ---
    # each value: list of (x, y) sample points that should be solidly blue/red
    banner_blue_pts: list[tuple[int, int]]
    banner_red_pts: list[tuple[int, int]]
    score_boxes: dict[str, tuple[int, int, int, int]]  # "blue"/"red" -> (x0,y0,x1,y1)

    # --- helmet positions keyed by team_size ---
    # {2: {"blue": [(x,y),...], "red": [(x,y),...]}, 4: {...}, ...}
    helmet_positions: dict[int, dict[str, list[tuple[int, int]]]]

    # --- scoreboard detection & grid ---
    scoreboard: dict[str, Any]

    # --- tunable thresholds ---
    white_thresh: int = 190     # helmet alive threshold
    gray_thresh: int = 80       # helmet dead threshold
    icon_thresh: float = 0.62   # template-match confidence floor
    merge_gap_s: float = 1.0    # max gap to merge repeated row sightings

    # path to icon template PNGs (absolute or relative to this file's directory)
    templates_dir: str = "templates"

    # ------------------------------------------------------------------ load

    @classmethod
    def load(cls, name_or_path: str | Path) -> "LayoutProfile":
        """Load by name (looks in profiles/) or by explicit path."""
        p = Path(name_or_path)
        if not p.suffix:                        # bare name -> add .json
            p = _PROFILES_DIR / f"{name_or_path}.json"
        if not p.exists():
            raise FileNotFoundError(f"Layout profile not found: {p}")
        with p.open(encoding="utf-8") as f:
            return cls._from_dict(json.load(f))

    @classmethod
    def _from_dict(cls, d: dict) -> "LayoutProfile":
        def t4(v):  return tuple(v) if len(v) == 4 else tuple(v)
        def t2(v):  return tuple(v)
        def pts(lst): return [tuple(xy) for xy in lst]

        score_boxes = {team: t4(coords) for team, coords in d["score_boxes"].items()}

        helmet_positions: dict[int, dict] = {}
        for size_str, teams in d["helmet_positions"].items():
            helmet_positions[int(size_str)] = {
                team: pts(positions) for team, positions in teams.items()
            }

        return cls(
            name=d["name"],
            resolution=t2(d["resolution"]),
            feed_box=t4(d["feed_box"]),
            row_left_min=d.get("row_left_min", 5),
            row_left_max=d.get("row_left_max", 40),
            remaining_box=t4(d["remaining_box"]),
            banner_blue_pts=pts(d["banner_blue_pts"]),
            banner_red_pts=pts(d["banner_red_pts"]),
            score_boxes=score_boxes,
            helmet_positions=helmet_positions,
            scoreboard=d.get("scoreboard", {}),
            white_thresh=d.get("white_thresh", 190),
            gray_thresh=d.get("gray_thresh", 80),
            icon_thresh=d.get("icon_thresh", 0.62),
            merge_gap_s=d.get("merge_gap_s", 1.0),
            templates_dir=d.get("templates_dir", "templates"),
        )

    # ---------------------------------------------------------------- helpers

    def helmet_pos_for_size(self, team_size: int) -> dict[str, list[tuple[int, int]]]:
        """Return helmet positions for team_size; fall back to the largest configured size."""
        if team_size in self.helmet_positions:
            return self.helmet_positions[team_size]
        best = max(self.helmet_positions.keys())
        return self.helmet_positions[best]

    @property
    def templates_path(self) -> Path:
        td = Path(self.templates_dir)
        if td.is_absolute():
            return td
        return Path(__file__).parent / td
