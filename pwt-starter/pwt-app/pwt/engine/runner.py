"""Capture thread -> bounded queue -> analyser (engine) loop (brief §4.2).

Live sources drop the OLDEST frame when the analyser falls behind (and count it); replay never drops."""
import queue, threading, time


def run(source, engine, max_queue=24, stop_event=None, on_frame=None):
    """Capture thread -> queue -> engine.

    *on_frame(n, t)* is called after each processed frame, for a progress bar.
    It must be cheap and must not raise; it runs on the analyser thread.
    """
    q = queue.Queue(maxsize=max_queue)
    stats = dict(frames=0, dropped=0)

    def capture():
        try:
            for item in source.frames():
                if stop_event is not None and stop_event.is_set(): break
                if getattr(source, "live", False):
                    while True:
                        try:
                            q.put_nowait(item); break
                        except queue.Full:
                            try: q.get_nowait(); stats["dropped"] += 1
                            except queue.Empty: pass
                else:
                    q.put(item)
        finally:
            q.put(None)

    th = threading.Thread(target=capture, daemon=True)
    t0 = time.perf_counter()
    th.start()
    while True:
        item = q.get()
        if item is None: break
        engine.process(*item)
        stats["frames"] += 1
        if on_frame is not None:
            on_frame(stats["frames"], item[0])
        if stop_event is not None and stop_event.is_set(): break
    summary = engine.finish()
    summary.update(stats, wall_s=round(time.perf_counter() - t0, 1))
    return summary
