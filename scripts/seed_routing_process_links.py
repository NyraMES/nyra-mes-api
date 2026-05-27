"""One-time seed: link existing routing_operation rows to process_library.

Run after process_library and data_capture templates are loaded.
Does not create processes — only sets routing_operation.process_id where null.

Usage:
  PYTHONPATH=. python scripts/seed_routing_process_links.py
  PYTHONPATH=. python scripts/seed_routing_process_links.py --dry-run
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from app.db.database import SessionLocal


# Map operation_name (case-insensitive substring) -> process_id
NAME_HINTS: list[tuple[str, str]] = [
    ("mould", "PROC_MOULDING"),
    ("mold", "PROC_MOULDING"),
    ("melting", "PROC_MELTING"),
    ("melt", "PROC_MELTING"),
    ("pour", "PROC_POURING"),
    ("fettling", "PROC_FETTLING"),
    ("fettle", "PROC_FETTLING"),
    ("final", "PROC_FINAL_QC"),
    ("inspect", "PROC_FINAL_QC"),
    ("qc", "PROC_FINAL_QC"),
    ("raw material", "PROC_FINAL_QC"),
]


def suggest_process_id(operation_name: str) -> str | None:
    name = (operation_name or "").lower()
    for hint, process_id in NAME_HINTS:
        if hint in name:
            return process_id
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT id, operation_code, operation_name, process_id
                FROM mst.routing_operation
                ORDER BY operation_sequence, operation_code
                """
            )
        ).all()

        updated = 0
        skipped = 0
        for row_id, op_code, op_name, current_pid in rows:
            if current_pid:
                skipped += 1
                continue
            pid = suggest_process_id(op_name)
            if not pid:
                print(f"SKIP  {op_code} ({op_name}) — no matching process hint")
                continue
            exists = db.execute(
                text("SELECT 1 FROM mst.process_library WHERE process_id = :pid"),
                {"pid": pid},
            ).scalar()
            if not exists:
                print(f"SKIP  {op_code} ({op_name}) — process {pid} not in library")
                continue
            print(f"LINK  {op_code} ({op_name}) -> {pid}")
            if not args.dry_run:
                db.execute(
                    text(
                        """
                        UPDATE mst.routing_operation
                        SET process_id = :pid
                        WHERE id = :id AND process_id IS NULL
                        """
                    ),
                    {"pid": pid, "id": row_id},
                )
                updated += 1

        if not args.dry_run:
            db.commit()
        print(f"Done. updated={updated} already_linked={skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
