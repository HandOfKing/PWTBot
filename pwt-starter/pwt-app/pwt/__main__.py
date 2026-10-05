import sys
from .cli import main

# sys.exit, not a bare call: the HUD guard returns 2 to refuse mismatched
# footage (ARCHITECTURE.md invariant 8), and a bare main() discarded it, so the
# process exited 0 and any caller checking the status read a refusal as success.
sys.exit(main())
