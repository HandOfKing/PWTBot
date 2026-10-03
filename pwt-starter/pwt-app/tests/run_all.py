"""Run every test without pytest:  python tests/run_all.py"""
import importlib, sys, time, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _util import Skip

failed = 0
for f in sorted(Path(__file__).parent.glob("test_*.py")):
    mod = importlib.import_module(f.stem)
    for name in [n for n in dir(mod) if n.startswith("test_")]:
        t = time.time()
        try:
            getattr(mod, name)(); print(f"ok    {f.stem}.{name}  ({time.time() - t:.1f}s)")
        except Skip as e:
            print(f"skip  {f.stem}.{name}: {e}")
        except Exception:
            failed += 1; print(f"FAIL  {f.stem}.{name}"); traceback.print_exc()
print("FAILED" if failed else "all passed", f"({failed} failures)")
sys.exit(1 if failed else 0)
