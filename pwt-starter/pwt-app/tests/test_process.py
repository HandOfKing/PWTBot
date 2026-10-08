"""pwt.process -- the one-call pipeline behind the desktop app.

The first test needs no recording (it writes a tiny synthetic video), so it
runs anywhere, including the packaged app's self-test. The others use
clips/Video_Project_9.mp4 and skip without it.
"""
import os, tempfile, threading
from pathlib import Path
import cv2, numpy as np
from _util import skip
from pwt import process

CLIP = Path(__file__).resolve().parents[1] / "clips" / "Video_Project_9.mp4"


def _tmp_db():
    d = Path(tempfile.mkdtemp(prefix="pwt_test_"))
    return d, d / "pwt.db"


def synthetic_video(path, seconds=2, fps=10):
    """A plain gray 1080p clip: decodes like a recording, contains no game."""
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (1920, 1080))
    frame = np.full((1080, 1920, 3), 90, np.uint8)
    for i in range(seconds * fps):
        cv2.putText(frame, f"{i:03d}", (900, 540), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 255), 5)
        w.write(frame)
        frame[:] = 90
    w.release()
    return path


def test_no_game_in_video_is_refused_then_reported():
    d, dbp = _tmp_db()
    vid = synthetic_video(d / "blank.mp4")
    assert abs(process.video_info(vid)[0] - 2.0) < 0.2
    r = process.process(vid, db_path=dbp, out_dir=d)
    assert not r.ok and not r.layout_ok and "FAIL" in r.layout_report      # stage 0 refuses
    seen = []
    r = process.process(vid, db_path=dbp, out_dir=d, force=True, on_progress=lambda a, b: seen.append(a))
    assert not r.ok and r.error and r.match_id is None                      # ran, found no round
    assert seen and r.log_path and r.log_path.exists()


def test_wrong_layout_is_refused():
    """Footage that does not match the layout is refused, not processed into plausible junk.
    There is one layout, so a copy of it with every HUD box moved 300 px down stands in for
    another one (a different emulator window, a different resolution)."""
    if not CLIP.exists(): skip(f"test clip not found at {CLIP}")
    import json
    from pwt import profiles
    d, dbp = _tmp_db()
    prof = json.loads((profiles.BUILTIN / f"{profiles.DEFAULT}.json").read_text(encoding="utf-8"))
    def down(box): return [box[0], box[1] + 300, box[2], box[3] + 300]
    prof["remaining_box"] = down(prof["remaining_box"]); prof["feed"]["box"] = down(prof["feed"]["box"])
    for k in ("blue_score_box", "red_score_box"): prof["banner"][k] = down(prof["banner"][k])
    for team in prof["banner"]["helmets"]["6"].values():
        for pt in team: pt[1] += 300
    moved = d / "moved.json"; moved.write_text(json.dumps(prof), encoding="utf-8")
    r = process.process(CLIP, profile_name=str(moved), db_path=dbp, out_dir=d,
                        roster=["TheWolverine", "RGODxEMPEROR", "KG696969"])
    assert not r.ok and not r.layout_ok


def test_stop_keeps_the_partial_match():
    if not CLIP.exists(): skip(f"test clip not found at {CLIP}")
    d, dbp = _tmp_db()
    stop = threading.Event()
    def prog(done, total):
        if done >= 45: stop.set()
    r = process.process(CLIP, db_path=dbp, out_dir=d, stop_event=stop, on_progress=prog,
                        roster=["KG696969", "Makjets69", "Sarthakkkd", "BruceWayne³"])
    assert r.ok and r.cancelled and r.xlsx_path.exists() and r.csv_path.exists()
    import sqlite3
    st = sqlite3.connect(dbp).execute("SELECT status FROM matches WHERE id=?", (r.match_id,)).fetchone()[0]
    assert st == "interrupted"
    assert r.counts["eliminations"] >= 2                                    # 36.1 s and 41.2 s


def test_same_recording_twice_asks_then_replaces():
    d, dbp = _tmp_db()
    vid = synthetic_video(d / "blank.mp4")
    from pwt import db
    conn = db.connect(dbp)
    lm = db.LiveMatch(conn, recorded_at=db.recorded_at_from_file(vid), source_file=vid.name)
    lm.finish()
    r = process.process(vid, db_path=dbp, out_dir=d, force=True)
    assert not r.ok and r.earlier_match == lm.id                            # asks first
    r = process.process(vid, db_path=dbp, out_dir=d, force=True, replace=True)
    assert r.earlier_match is None and db.find_match(conn, vid.name, db.recorded_at_from_file(vid)) is None
