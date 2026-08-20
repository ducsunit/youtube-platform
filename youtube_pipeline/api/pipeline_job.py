"""Internal worker used by the Web UI to run one resource-pack job.

This is intentionally not a public CLI entrypoint. The API runner starts this
module as a child process so the job survives an API-server restart while all
user-facing control remains in the Web UI.
"""
from __future__ import annotations

import sys

from ..resource_pack.cli import resource_main


def main() -> int:
    return resource_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
