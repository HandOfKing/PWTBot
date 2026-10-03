"""Phase 1 go/no-go (docs/PWT_BRIEF.md §12): can this laptop capture GameLoop at 12 fps and run the REAL engine
on every frame without hurting the game?

On the Windows laptop, while spectating a room in GameLoop (run the terminal as administrator if GameLoop is):
    python tools/capture_bench.py --seconds 180
Anywhere (simulates live capture by playing a recording at real-time speed):
    python tools/capture_bench.py --replay clips/Video_Project_7.mp4

Writes bench_out/report.txt, a full frame every 10 s and the first frame of each scoreboard (for calibrating the
fullscreen layout). Uses a throwaway database, so your real stats are untouched.
"""
import argparse, statistics, sys, tempfile, threading, time
from pathlib import Path
import cv2, numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pwt import db, profiles
from pwt.capture.sources import FileReplaySource, LiveScreenSource
from pwt.engine.engine import Engine
from pwt.engine.runner import run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=180)
    ap.add_argument("--fps", type=float, default=12)
    ap.add_argument("--profile", default="gameloop-windowed-1080p")
    ap.add_argument("--replay", help="simulate with a recording played at real-time speed")
    ap.add_argument("--out", default="bench_out")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(exist_ok=True)
    prof = profiles.load(a.profile)
    tmp = Path(tempfile.mkdtemp())
    conn = db.connect(tmp / "bench.db")

    if a.replay:
        src = FileReplaySource(a.replay, fps=a.fps, realtime=True); src.live = True     # behave like live: may drop
    else:
        src = LiveScreenSource(region=prof.get("capture_region"), fps=a.fps)
    eng = Engine(prof, conn, source_file="bench", data_dir=tmp, log=lambda *x: None)

    times, stamps, walls, boards, state = [], [], [], [], {"s": None, "since": 0.0, "black": 0, "saved": -10.0}
    orig = eng.process

    def timed(t, frame):
        c0 = time.perf_counter()
        orig(t, frame)
        times.append((time.perf_counter() - c0) * 1000); stamps.append(t); walls.append(time.perf_counter())
        if len(stamps) <= 12 and float(frame.mean()) < 3: state["black"] += 1
        st = eng.state
        if st != state["s"]:
            if state["s"] == "SCOREBOARD": boards.append((state["since"], t - state["since"]))
            if st == "SCOREBOARD": cv2.imwrite(str(out / f"scoreboard_{t:07.1f}s.png"), frame)
            print(f"{t:7.1f}s  {state['s']} -> {st}")
            state.update(s=st, since=t)
        if t - state["saved"] >= 10:
            cv2.imwrite(str(out / f"frame_{t:07.1f}s.png"), frame); state["saved"] = t
    eng.process = timed

    try:
        import psutil
        proc = psutil.Process(); proc.cpu_percent(None); psutil.cpu_percent(None)
    except ImportError:
        psutil = proc = None
    cpu_p, cpu_s, ram, stop = [], [], [], threading.Event()

    def sample():
        while not stop.wait(1.0):
            if psutil:
                cpu_p.append(proc.cpu_percent(None) / psutil.cpu_count()); cpu_s.append(psutil.cpu_percent(None))
                ram.append(proc.memory_info().rss / 2**20)
    threading.Thread(target=sample, daemon=True).start()
    timer = threading.Timer(a.seconds, lambda: (stop.set(), getattr(src, "stop", lambda: None)()))
    timer.start()
    print(f"running the engine on {'replay ' + a.replay if a.replay else 'live capture'} at {a.fps} fps "
          f"for up to {a.seconds:.0f}s - keep spectating normally")
    t0 = time.perf_counter()
    summary = run(src, eng, stop_event=stop)
    wall = time.perf_counter() - t0
    stop.set(); timer.cancel()

    period = 1000 / a.fps
    achieved = (len(walls) - 1) / max(walls[-1] - walls[0], 1e-6) if len(walls) > 1 else 0.0
    lines = [
        f"source               : {'replay (real-time) ' + a.replay if a.replay else 'live capture'}",
        f"target fps           : {a.fps}",
        f"frames analysed      : {len(stamps)}  -> {achieved:.2f} fps",
        f"frames dropped       : {summary.get('dropped', 0)}  ({100 * summary.get('dropped', 0) / max(len(stamps), 1):.1f}%)",
        f"engine per frame     : mean {statistics.mean(times):.1f} ms, p95 {np.percentile(times, 95):.1f} ms "
        f"(budget {period:.0f} ms)",
        f"black frames at start: {state['black']}/12" + ("  <-- run as admin / same GPU as GameLoop" if state['black'] > 6 else ""),
    ]
    if cpu_p:
        lines += [f"CPU, this program    : mean {statistics.mean(cpu_p):.1f}% of the whole CPU",
                  f"CPU, whole system    : mean {statistics.mean(cpu_s):.0f}%, max {max(cpu_s):.0f}%",
                  f"RAM, this program    : max {max(ram):.0f} MB"]
    lines += [f"rounds / events seen : {summary.get('rounds')} / {summary.get('events')}",
              f"scoreboards seen     : {len(boards)}"] + [f"   at {s:7.1f}s, on screen {d:.1f}s" for s, d in boards]
    drop_pct = summary.get("dropped", 0) / max(len(stamps), 1)
    ok = achieved >= 0.95 * a.fps and drop_pct < 0.01 and np.percentile(times, 95) < period / 2 and state["black"] <= 6
    lines += ["", "GO" if ok else "NOT YET - see the numbers above",
              "Also check by eye: did the game stutter while this ran? Does the mouse wheel scroll a scoreboard, or only a drag?"]
    (out / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
