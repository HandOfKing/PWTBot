"""PWT desktop app: pick a recording, get the eliminations table.

Tkinter only (it ships with Python), so the Windows bundle stays small. All the
work happens in pwt.process on a worker thread; this file is just the window.

    PWT.exe                    the app
    PWT.exe --selftest OUT     check the packaged app works (the build runs this)
"""
from __future__ import annotations
import os, queue, subprocess, sys, threading, time, traceback
from pathlib import Path

if not getattr(sys, "frozen", False):                   # running from source: make `pwt` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pwt import __version__, db, export_excel, process   # noqa: E402

DETAIL = [  # (label, fps)
    ("Standard - 12 fps (recommended)", 12),
    ("Thorough - 24 fps (about 1.5x slower, catches a few more knocks)", 24),
    ("Quick - 4 fps (misses rows at round ends)", 4),
]


def app_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def bundled_roster():
    """roster.txt next to the app (one name per line), used when the database has no players yet."""
    p = app_dir() / "roster.txt"
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def open_path(p):
    p = str(p)
    if os.name == "nt":
        os.startfile(p)                                   # noqa: (Windows only)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def mmss(s):
    s = max(0, int(s))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.root = tk, ttk, root
        root.title(f"PWT {__version__} - match stats from your recordings")
        root.minsize(780, 620)
        self.q = queue.Queue()
        self.worker, self.stop, self.result = None, None, None
        self.t_start, self.last_run = None, None
        self.conn = db.connect()
        db.recover_interrupted(self.conn)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_run = ttk.Frame(nb, padding=12)
        self.tab_matches = ttk.Frame(nb, padding=12)
        nb.add(self.tab_run, text="  Process a recording  ")
        nb.add(self.tab_matches, text="  Matches  ")
        nb.bind("<<NotebookTabChanged>>", lambda e: self.refresh_matches())
        self._build_run(self.tab_run)
        self._build_matches(self.tab_matches)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll)

    # ------------------------------------------------------------ process tab
    def _build_run(self, f):
        tk, ttk = self.tk, self.ttk
        f.columnconfigure(1, weight=1)
        r = 0
        ttk.Label(f, text="Recording").grid(row=r, column=0, sticky="w", pady=3)
        self.v_path = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_path).grid(row=r, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="Browse...", command=self.browse).grid(row=r, column=2, sticky="ew")
        r += 1
        ttk.Label(f, text="Layout").grid(row=r, column=0, sticky="w", pady=3)
        lay = ttk.Frame(f); lay.grid(row=r, column=1, columnspan=2, sticky="w", padx=6)
        self.v_profile = tk.StringVar(value=process.DEFAULT_PROFILE)
        ttk.Combobox(lay, textvariable=self.v_profile, values=process.profile_names(), state="readonly",
                     width=34).pack(side="left")
        ttk.Label(lay, text="   Players per team").pack(side="left")
        self.v_team = tk.IntVar(value=6)
        ttk.Spinbox(lay, from_=2, to=8, textvariable=self.v_team, width=4, state="readonly").pack(side="left", padx=4)
        r += 1
        ttk.Label(f, text="Detail").grid(row=r, column=0, sticky="nw", pady=3)
        det = ttk.Frame(f); det.grid(row=r, column=1, columnspan=2, sticky="w", padx=6)
        self.v_fps = tk.IntVar(value=12)
        for label, fps in DETAIL:
            ttk.Radiobutton(det, text=label, value=fps, variable=self.v_fps).pack(anchor="w")
        r += 1
        ttk.Label(f, text="Player names").grid(row=r, column=0, sticky="nw", pady=3)
        box = ttk.Frame(f); box.grid(row=r, column=1, sticky="nsew", padx=6)
        self.t_names = tk.Text(box, height=7, width=40, wrap="none", undo=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.t_names.yview)
        self.t_names.configure(yscrollcommand=sb.set)
        self.t_names.pack(side="left", fill="both", expand=True); sb.pack(side="left", fill="y")
        side = ttk.Frame(f); side.grid(row=r, column=2, sticky="n")
        ttk.Button(side, text="Load list...", command=self.load_names).pack(fill="x")
        names = process.saved_roster(self.conn) or bundled_roster()
        self.t_names.insert("1.0", "\n".join(names))
        r += 1
        ttk.Label(f, text="One name per line, spelled as in the game. Every name read from the kill feed is "
                          "matched against this list.", foreground="#555").grid(row=r, column=1, columnspan=2,
                                                                                sticky="w", padx=6)
        r += 1
        ttk.Label(f, text="Save results to").grid(row=r, column=0, sticky="w", pady=(10, 3))
        self.v_out = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_out).grid(row=r, column=1, sticky="ew", padx=6, pady=(10, 3))
        ttk.Button(f, text="Change...", command=self.pick_out).grid(row=r, column=2, sticky="ew", pady=(10, 3))
        r += 1
        ttk.Label(f, text="Leave empty to save next to the recording.", foreground="#555").grid(
            row=r, column=1, columnspan=2, sticky="w", padx=6)
        r += 1
        btns = ttk.Frame(f); btns.grid(row=r, column=0, columnspan=3, sticky="w", pady=(12, 4))
        self.b_start = ttk.Button(btns, text="Start", command=self.start)
        self.b_start.pack(side="left")
        self.b_stop = ttk.Button(btns, text="Stop", command=self.request_stop, state="disabled")
        self.b_stop.pack(side="left", padx=6)
        r += 1
        self.pb = ttk.Progressbar(f, maximum=1000)
        self.pb.grid(row=r, column=0, columnspan=3, sticky="ew")
        r += 1
        self.v_status = tk.StringVar(value="Pick a recording and press Start.")
        ttk.Label(f, textvariable=self.v_status).grid(row=r, column=0, columnspan=3, sticky="w", pady=3)
        r += 1
        res = ttk.LabelFrame(f, text="Result", padding=8)
        res.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(6, 4))
        res.columnconfigure(0, weight=1)
        self.v_result = tk.StringVar(value="-")
        ttk.Label(res, textvariable=self.v_result, justify="left").grid(row=0, column=0, sticky="w")
        rb = ttk.Frame(res); rb.grid(row=0, column=1, sticky="e")
        self.b_xlsx = ttk.Button(rb, text="Open Excel", state="disabled",
                                 command=lambda: open_path(self.result.xlsx_path))
        self.b_folder = ttk.Button(rb, text="Open folder", state="disabled",
                                   command=lambda: open_path(self.result.xlsx_path.parent))
        self.b_xlsx.pack(side="left"); self.b_folder.pack(side="left", padx=6)
        r += 1
        f.rowconfigure(r, weight=1)
        lf = ttk.LabelFrame(f, text="Log", padding=4)
        lf.grid(row=r, column=0, columnspan=3, sticky="nsew")
        self.t_log = tk.Text(lf, height=8, wrap="none", state="disabled", font=("Consolas", 9))
        ls = ttk.Scrollbar(lf, orient="vertical", command=self.t_log.yview)
        self.t_log.configure(yscrollcommand=ls.set)
        self.t_log.pack(side="left", fill="both", expand=True); ls.pack(side="left", fill="y")

    def browse(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title="Pick a match recording",
                                       filetypes=[("Video", "*.mkv *.mp4 *.mov *.avi"), ("All files", "*.*")])
        if p: self.v_path.set(p)

    def pick_out(self):
        from tkinter import filedialog
        p = filedialog.askdirectory(title="Save results to")
        if p: self.v_out.set(p)

    def load_names(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title="Player names, one per line",
                                       filetypes=[("Text", "*.txt *.csv"), ("All files", "*.*")])
        if not p: return
        have = self.names()
        new = [l.strip().split(",")[0] for l in Path(p).read_text(encoding="utf-8-sig").splitlines() if l.strip()]
        merged = have + [n for n in new if n not in have]
        self.t_names.delete("1.0", "end")
        self.t_names.insert("1.0", "\n".join(merged))

    def names(self):
        out = []
        for l in self.t_names.get("1.0", "end").splitlines():
            n = l.strip()
            if n and n not in out: out.append(n)
        return out

    def log(self, line):
        self.t_log.configure(state="normal")
        self.t_log.insert("end", line + "\n")
        self.t_log.see("end")
        self.t_log.configure(state="disabled")

    def start(self, force=False, replace=False, ask=True):
        from tkinter import messagebox
        if self.worker and self.worker.is_alive(): return
        path = Path(self.v_path.get().strip().strip('"'))
        if not path.is_file():
            messagebox.showerror("PWT", "Pick a recording first."); return
        roster = self.names()
        if not roster and ask and not messagebox.askyesno(
                "PWT", "No player names given.\n\nNames will only be learned from the scoreboard, so most "
                       "eliminations will come out unnamed. Continue anyway?"):
            return
        self.last_run = dict(path=path, profile_name=self.v_profile.get(), roster=roster,
                             fps=int(self.v_fps.get()), team_size=int(self.v_team.get()),
                             out_dir=self.v_out.get().strip() or None, force=force, replace=replace)
        self.result, self.stop = None, threading.Event()
        self.b_start.configure(state="disabled"); self.b_stop.configure(state="normal")
        self.b_xlsx.configure(state="disabled"); self.b_folder.configure(state="disabled")
        self.pb.configure(value=0); self.v_result.set("-")
        self.v_status.set("Checking the layout (sampling the recording)...")
        self.t_start = time.perf_counter()
        args = dict(self.last_run, stop_event=self.stop,
                    on_progress=lambda d, t: self.q.put(("progress", d, t)),
                    on_log=lambda line: self.q.put(("log", line)))

        def work():
            try:
                self.q.put(("done", process.process(**args)))
            except Exception:
                self.q.put(("error", traceback.format_exc()))
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def request_stop(self):
        if self.stop: self.stop.set()
        self.v_status.set("Stopping... (the part processed so far is kept)")
        self.b_stop.configure(state="disabled")

    def poll(self):
        try:
            for _ in range(500):
                msg = self.q.get_nowait()
                if msg[0] == "log":
                    self.log(msg[1])
                elif msg[0] == "progress":
                    self._progress(msg[1], msg[2])
                elif msg[0] == "done":
                    self._finished(msg[1])
                elif msg[0] == "error":
                    self._failed(msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def _progress(self, done, total):
        self.pb.configure(value=1000 * done / total if total else 0)
        el = time.perf_counter() - self.t_start
        eta = (el / done * (total - done)) if done > 5 else None
        self.v_status.set(f"{mmss(done)} of {mmss(total)} processed"
                          + (f"  -  about {mmss(eta)} left" if eta is not None else ""))

    def _idle(self):
        self.b_start.configure(state="normal"); self.b_stop.configure(state="disabled")

    def _failed(self, tb):
        from tkinter import messagebox
        self._idle()
        self.log(tb)
        self.v_status.set("Something went wrong - see the log.")
        messagebox.showerror("PWT", "Processing failed:\n\n" + tb.strip().splitlines()[-1])

    def _finished(self, res):
        from tkinter import messagebox
        self._idle()
        self.result = res
        if res.earlier_match is not None:
            if messagebox.askyesno("PWT", "This recording was processed before.\n\n"
                                          "Replace the earlier result with a new one?"):
                self.start(force=self.last_run["force"], replace=True, ask=False)
            else:
                self.v_status.set("Kept the earlier result (see the Matches tab).")
            return
        if not res.layout_ok and not res.ok:
            self.v_status.set("The layout does not fit this recording.")
            if messagebox.askyesno("PWT - layout does not fit",
                                   res.layout_report + "\n\nRun anyway? Every row will be suspect."):
                self.start(force=True, replace=self.last_run["replace"], ask=False)
            return
        took = mmss(time.perf_counter() - self.t_start)
        if not res.ok:
            self.v_status.set(("Stopped. " if res.cancelled else "") + (res.error or "No table was produced."))
            return
        c = res.counts
        self.v_result.set(
            f"{c['eliminations']} eliminations in {c['rounds']} rounds  -  {c['named']} named, "
            f"{c['no_feed_row']} without a kill-feed row\n"
            f"{c['knocks']} knocks  -  {c['to_review']} rows flagged for review\n"
            f"Saved: {res.xlsx_path.name}  (+ events CSV and log)")
        self.b_xlsx.configure(state="normal"); self.b_folder.configure(state="normal")
        self.v_status.set(("Stopped early - partial result saved. " if res.cancelled else "Done. ")
                          + f"Took {took}.")
        self.pb.configure(value=1000)

    # ------------------------------------------------------------ matches tab
    def _build_matches(self, f):
        ttk = self.ttk
        f.columnconfigure(0, weight=1); f.rowconfigure(0, weight=1)
        cols = [("when", "Recorded", 140), ("file", "Recording", 240), ("rounds", "Rounds", 60),
                ("elims", "Eliminations", 90), ("review", "To review", 80), ("status", "Status", 100)]
        self.tv = ttk.Treeview(f, columns=[c[0] for c in cols], show="headings", selectmode="extended")
        for key, text, w in cols:
            self.tv.heading(key, text=text)
            self.tv.column(key, width=w, anchor="w" if key in ("when", "file", "status") else "center")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.grid(row=0, column=0, sticky="nsew"); sb.grid(row=0, column=1, sticky="ns")
        b = ttk.Frame(f); b.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(b, text="Export selected...", command=self.export_selected).pack(side="left")
        ttk.Button(b, text="Export all...", command=self.export_all).pack(side="left", padx=6)
        ttk.Button(b, text="Delete selected", command=self.delete_selected).pack(side="left")
        ttk.Button(b, text="Open data folder", command=lambda: open_path(db.data_dir())).pack(side="left", padx=6)
        ttk.Button(b, text="Refresh", command=self.refresh_matches).pack(side="left")
        self.refresh_matches()

    def refresh_matches(self):
        self.tv.delete(*self.tv.get_children())
        for m in db.list_matches(self.conn):
            self.tv.insert("", "end", iid=str(m["id"]),
                           values=(m["recorded_at"], m["source_file"], m["rounds_played"] or "",
                                   m["eliminations"], m["to_review"], m["status"]))

    def export_selected(self):
        from tkinter import filedialog, messagebox
        sel = self.tv.selection()
        if not sel:
            messagebox.showinfo("PWT", "Select a match first."); return
        if len(sel) == 1:
            m = self.conn.execute("SELECT recorded_at, source_file FROM matches WHERE id=?", (int(sel[0]),)).fetchone()
            p = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                             initialfile=f"{Path(m['source_file']).stem} - PWT.xlsx")
            if p: export_excel.export_match(self.conn, int(sel[0]), p); open_path(p)
        else:
            d = filedialog.askdirectory(title="Save one workbook per match to")
            if not d: return
            for mid in sel:
                m = self.conn.execute("SELECT source_file FROM matches WHERE id=?", (int(mid),)).fetchone()
                export_excel.export_match(self.conn, int(mid), Path(d) / f"{Path(m['source_file']).stem} - PWT.xlsx")
            open_path(d)

    def export_all(self):
        from tkinter import filedialog
        p = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                         initialfile="PWT - all matches.xlsx")
        if p: export_excel.export_range(self.conn, p); open_path(p)

    def delete_selected(self):
        from tkinter import messagebox
        sel = self.tv.selection()
        if sel and messagebox.askyesno("PWT", f"Delete {len(sel)} match(es) from the database?\n\n"
                                              "Exported Excel files are not touched."):
            for mid in sel: db.delete_match(self.conn, int(mid))
            self.refresh_matches()

    def on_close(self):
        from tkinter import messagebox
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("PWT", "A recording is still being processed. Stop and quit?"):
                return
            self.stop.set()
        self.root.destroy()


# ---------------------------------------------------------------- self-test
def selftest(out):
    """Checks the packaged app on the build machine: bundled files, OCR engine, video decode, the
    pipeline, the Excel export, and the window driven end to end. Exit code 0 = all passed."""
    import tempfile, cv2, numpy as np
    lines, ok = [], True

    def check(name, fn):
        nonlocal ok
        try:
            detail = fn()
            lines.append(f"ok    {name}" + (f": {detail}" if detail else ""))
        except Exception:
            ok = False
            lines.append(f"FAIL  {name}\n" + traceback.format_exc())

    tmp = Path(tempfile.mkdtemp(prefix="pwt_selftest_"))
    os.environ["PWT_DATA_DIR"] = str(tmp / "data")
    from pwt import profiles
    from pwt.readers import names

    check("version", lambda: __version__)
    check("profiles", lambda: ", ".join(process.profile_names()))
    def templates():
        prof = profiles.load(process.DEFAULT_PROFILE)
        from pwt.readers.feed import FeedReader
        n = len(FeedReader(prof).icons)
        assert n >= 3, f"only {n} icon templates"
        return f"{n} icons in {prof.templates}"
    check("templates", templates)
    def ocr():
        assert names._CMD, "no tesseract found"
        img = np.zeros((40, 400), np.uint8)
        cv2.putText(img, "TheWolverine", (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 1, 2)
        text = names.ocr_mask(img)
        n, sc = names.match(text.replace(" ", ""), ["TheWolverine", "KG696969", "Makjets69"])
        assert n == "TheWolverine", f"read {text!r}"
        return f"{names._CMD} read {text!r}"
    check("ocr engine", ocr)
    vid = tmp / "blank.mp4"
    def decode():
        w = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"mp4v"), 10, (1920, 1080))
        for i in range(20):
            w.write(np.full((1080, 1920, 3), 90, np.uint8))
        w.release()
        d, w_, h_ = process.video_info(vid)
        assert abs(d - 2.0) < 0.2 and (w_, h_) == (1920, 1080), (d, w_, h_)
        return f"{d:.1f} s {w_}x{h_}"
    check("video decode", decode)
    def pipeline():
        r = process.process(vid, out_dir=tmp, force=True)
        assert not r.ok and r.error and r.log_path.exists(), r
        return r.error
    check("pipeline", pipeline)
    def excel():
        conn = db.connect()
        lm = db.LiveMatch(conn, recorded_at="2026-10-05 20:00:00", source_file="selftest.mkv")
        lm.start_round(1, 0.0)
        lm.add_event(dict(true_time_s=5.0, feed_time_s=6.0, time_source="Remaining drop", event_type="kill",
                          killer="DeathwishツSpy", victim="BruceWayne³", round_no=1))
        lm.end_round(1, end_s=10.0, winner_team="blue")
        lm.finish()
        p = tmp / "selftest.xlsx"
        export_excel.export_match(conn, lm.id, p)
        process.write_events_csv(conn, lm.id, tmp / "selftest.csv")
        assert p.stat().st_size > 1000
        return f"{p.stat().st_size} bytes"
    check("excel export", excel)
    def window():
        import tkinter as tk
        root = tk.Tk(); root.withdraw()
        app = App(root)
        app.v_path.set(str(vid))
        app.t_names.delete("1.0", "end"); app.t_names.insert("1.0", "TheWolverine\nKG696969")
        app.start(force=True, ask=False)
        t0 = time.time()
        while (app.worker.is_alive() or not app.q.empty()) and time.time() - t0 < 120:
            root.update(); time.sleep(0.05)
        for _ in range(5):
            root.update(); time.sleep(0.12)                 # let poll() drain the queue
        status = app.v_status.get()
        app.refresh_matches()
        root.destroy()
        assert app.result is not None and "No round" in status, status
        return status
    check("window", window)

    report = "\n".join([f"PWT {__version__} self-test: {'PASS' if ok else 'FAIL'}"] + lines)
    Path(out).write_text(report, encoding="utf-8")
    return 0 if ok else 1


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2] if len(sys.argv) > 2 else "selftest.txt"))
    import tkinter as tk
    root = tk.Tk()
    try:
        from tkinter import ttk
        style = ttk.Style(root)
        if "vista" in style.theme_names(): style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
