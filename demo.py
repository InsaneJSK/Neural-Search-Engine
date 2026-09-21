"""Interactive local demo: run `uv run demo.py`, then enter search queries."""

import sys

from nse.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main(["interactive", *sys.argv[1:]]))
