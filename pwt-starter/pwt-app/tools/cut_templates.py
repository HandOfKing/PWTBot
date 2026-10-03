"""Cut the starter templates and test fixtures from the 2026-10-01 test clip (windowed 1080p layout).

    python tools/cut_templates.py clips/Video_Project_7.mp4

Re-run with your own coordinates when making a new layout profile (fullscreen, bigger feed); the times and
boxes below are what was measured on the test clip (docs/PWT_BRIEF.md §3, §11).
"""
import sys
from pathlib import Path
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pwt.readers.mask import white_mask
from pwt.readers.digits import DigitReader

T = ROOT / "pwt" / "templates"
FIX = ROOT / "tests" / "fixtures"


def frame_at(cap, t):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    if not ok: raise RuntimeError(f"no frame at {t}s")
    return f


def main(clip):
    cap = cv2.VideoCapture(str(clip))
    (T / "icons").mkdir(parents=True, exist_ok=True)

    # 1. kill-feed icons, as white-text masks of the feed box, padded 3 px (frame with knock + tombstone rows)
    f = frame_at(cap, 14.833)
    fx0, fy0, fx1, fy1 = 100, 215, 760, 480
    m = white_mask(f[fy0:fy1, fx0:fx1]) * 255
    for name, (x0, x1, y0, y1) in {"weapon_UMP45": (214, 248, 400, 418), "icon_knock": (271, 299, 400, 418),
                                   "icon_tombstone": (225, 241, 444, 462)}.items():
        cv2.imwrite(str(T / "icons" / f"{name}.png"), m[y0 - 3 - fy0:y1 + 3 - fy0, x0 - 3 - fx0:x1 + 3 - fx0])

    # 2. scoreboard header ("Rank  Team  Wins  Player")
    board = frame_at(cap, 21.0)
    cv2.imwrite(str(T / "scoreboard_header.png"), cv2.cvtColor(board[195:232, 180:900], cv2.COLOR_BGR2GRAY))

    # 3. digit glyphs - one folder per font
    db = DigitReader(T / "digits_board")
    cell = lambda im, yc, x0, x1: im[yc - 20:yc + 20, x0:x1]
    db.harvest(cell(board, 287, 1628, 1750), "200")        # TheWolverine damage
    db.harvest(cell(board, 451, 1628, 1750), "52")         # RGODxEMPEROR damage
    db.harvest(cell(board, 327, 330, 400), "1")            # Team column
    db.harvest(cell(board, 491, 330, 400), "2")
    zeros = frame_at(cap, 19.54)
    for yc, x0, x1 in [(369, 1100, 1220), (533, 1100, 1220), (533, 1232, 1352)]:
        db.harvest(cell(zeros, yc, x0, x1), "0")

    dr = DigitReader(T / "digits_remaining")
    for t, v in [(10.0, "4"), (13.267, "3"), (14.0, "2")]:
        dr.harvest(frame_at(cap, t)[60:88, 184:210], v)

    dn = DigitReader(T / "digits_banner")
    dn.harvest(frame_at(cap, 10.0)[66:116, 772:808], "0")    # blue score before the round is won
    dn.harvest(frame_at(cap, 13.6)[66:116, 772:808], "1")    # blue score after
    dn.harvest(frame_at(cap, 10.0)[66:116, 1118:1156], "0")  # red score

    # 4. test fixtures (full frames)
    FIX.mkdir(parents=True, exist_ok=True)
    for t, name in [(12.875, "live_knock_row"), (17.0, "round_end_dimmed"), (20.5, "scoreboard_a"),
                    (21.0, "scoreboard_b"), (13.267, "remaining_3"), (14.0, "remaining_2_helmets_gray")]:
        cv2.imwrite(str(FIX / f"{name}.jpg"), frame_at(cap, t), [cv2.IMWRITE_JPEG_QUALITY, 92])
    print("templates:", sorted(p.relative_to(T).as_posix() for p in T.rglob("*.png")))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ROOT / "clips" / "Video_Project_7.mp4")
