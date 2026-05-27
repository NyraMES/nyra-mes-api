"""CLI seed for Playwright E2E — prints JSON context on stdout.

Usage:
  python tests/e2e_seed.py [--with-po]
"""

from __future__ import annotations

import argparse
import json

from tests.e2e_seed_utils import build_seed_codes, seed_production_order_with_lot, seed_workflow_context


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--with-po",
        action="store_true",
        help="Also create production order + single lot",
    )
    args = parser.parse_args()
    ctx = seed_workflow_context(build_seed_codes())
    if args.with_po:
        ctx = seed_production_order_with_lot(ctx)
    print(json.dumps(ctx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
