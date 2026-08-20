"""Start the Web UI API server.

Production runs are started from the Web UI. The pipeline worker is an
internal module launched by the API runner and is intentionally separate from
this package entrypoint.
"""

from .api import main
import sys

argv = sys.argv[1:]
# Keep the existing start script compatible while the public CLI entrypoint is
# removed: `api-server` is now only a legacy alias for starting the Web API.
if argv and argv[0] == "api-server":
    argv = argv[1:]

raise SystemExit(main(argv))
