"""CLI cleanup for Playwright E2E seed data.

Usage:
  python tests/e2e_cleanup.py '{"order_line_pk": 1, ...}'
"""

from __future__ import annotations

import json
import sys

from tests.e2e_seed_utils import cleanup_seed_context


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: e2e_cleanup.py '<json-context>'", file=sys.stderr)
        return 1
    ctx = json.loads(sys.argv[1])
    cleanup_seed_context(ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
