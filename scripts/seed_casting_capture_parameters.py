"""Seed capture parameters for standard casting route steps (Process → Data to capture).

Usage:
  PYTHONPATH=. python scripts/seed_casting_capture_parameters.py
  PYTHONPATH=. python scripts/seed_casting_capture_parameters.py --dry-run
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from app.db.database import SessionLocal

# Process (route step) → fields to capture during execution
CASTING_CAPTURE: dict[str, list[dict]] = {
    "PROC_MOULDING": [
        {"field_sequence": 10, "field_name": "sand_type", "field_label": "Sand type", "field_type": "text"},
        {"field_sequence": 20, "field_name": "mould_id", "field_label": "Mould ID", "field_type": "text"},
        {"field_sequence": 30, "field_name": "moisture_percent", "field_label": "Moisture %", "field_type": "number", "unit_of_measure": "%"},
        {"field_sequence": 40, "field_name": "mould_hardness", "field_label": "Mould hardness", "field_type": "number"},
    ],
    "PROC_MELTING": [
        {"field_sequence": 10, "field_name": "temperature", "field_label": "Furnace temp", "field_type": "number", "unit_of_measure": "°C"},
        {"field_sequence": 20, "field_name": "heat_number", "field_label": "Heat number", "field_type": "text"},
        {"field_sequence": 30, "field_name": "carbon_percent", "field_label": "Carbon %", "field_type": "number", "unit_of_measure": "%"},
        {"field_sequence": 40, "field_name": "silicon_percent", "field_label": "Silicon %", "field_type": "number", "unit_of_measure": "%"},
    ],
    "PROC_POURING": [
        {"field_sequence": 10, "field_name": "pouring_temperature", "field_label": "Pouring temp", "field_type": "number", "unit_of_measure": "°C"},
        {"field_sequence": 20, "field_name": "ladle_id", "field_label": "Ladle ID", "field_type": "text"},
        {"field_sequence": 30, "field_name": "pouring_time", "field_label": "Pouring time", "field_type": "number", "unit_of_measure": "min"},
    ],
    "PROC_FETTLING": [
        {"field_sequence": 10, "field_name": "rework_qty", "field_label": "Rework qty", "field_type": "number"},
        {"field_sequence": 20, "field_name": "scrap_qty", "field_label": "Scrap qty", "field_type": "number"},
        {"field_sequence": 30, "field_name": "operator", "field_label": "Operator", "field_type": "text"},
    ],
}

TEMPLATE_NAMES = {
    "PROC_MOULDING": "Moulding — data to capture",
    "PROC_MELTING": "Melting — data to capture",
    "PROC_POURING": "Pouring — data to capture",
    "PROC_FETTLING": "Fettling — data to capture",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        for process_id, fields in CASTING_CAPTURE.items():
            proc = db.execute(
                text("SELECT 1 FROM mst.process_library WHERE process_id = :pid"),
                {"pid": process_id},
            ).scalar()
            if not proc:
                print(f"SKIP {process_id} — process not in library")
                continue

            template_id = db.execute(
                text(
                    """
                    SELECT template_id FROM mst.data_capture_template
                    WHERE process_id = :pid AND is_active = true
                    ORDER BY template_sequence NULLS LAST, template_id
                    LIMIT 1
                    """
                ),
                {"pid": process_id},
            ).scalar()

            if not template_id:
                template_id = f"DCT_{process_id.replace('PROC_', '')}_001"
                print(f"CREATE template {template_id} for {process_id}")
                if not args.dry_run:
                    db.execute(
                        text(
                            """
                            INSERT INTO mst.data_capture_template
                                (template_id, process_id, template_name, template_sequence,
                                 capture_stage, is_active)
                            VALUES
                                (:tid, :pid, :name, 10, 'execution', true)
                            ON CONFLICT (template_id) DO NOTHING
                            """
                        ),
                        {
                            "tid": template_id,
                            "pid": process_id,
                            "name": TEMPLATE_NAMES[process_id],
                        },
                    )
            else:
                print(f"USE template {template_id} for {process_id}")

            for field in fields:
                row = db.execute(
                    text(
                        """
                        SELECT field_id FROM mst.data_capture_field
                        WHERE template_id = :tid AND field_name = :fname
                        """
                    ),
                    {"tid": template_id, "fname": field["field_name"]},
                ).scalar()
                if row:
                    print(f"  OK   {field['field_label']}")
                    if not args.dry_run:
                        db.execute(
                            text(
                                """
                                UPDATE mst.data_capture_field
                                SET field_label = :flabel, field_type = :ftype,
                                    unit_of_measure = :uom
                                WHERE field_id = :fid
                                """
                            ),
                            {
                                "fid": row,
                                "flabel": field["field_label"],
                                "ftype": field["field_type"],
                                "uom": field.get("unit_of_measure"),
                            },
                        )
                    continue

                next_seq = db.execute(
                    text(
                        """
                        SELECT COALESCE(MAX(field_sequence), 0) + 10
                        FROM mst.data_capture_field WHERE template_id = :tid
                        """
                    ),
                    {"tid": template_id},
                ).scalar()
                seq = field.get("field_sequence") or next_seq
                # Avoid sequence collision
                while db.execute(
                    text(
                        "SELECT 1 FROM mst.data_capture_field WHERE template_id = :tid AND field_sequence = :seq"
                    ),
                    {"tid": template_id, "seq": seq},
                ).scalar():
                    seq += 10

                field_id = f"DCF_{process_id.replace('PROC_', '')}_{field['field_name'].upper()[:12]}"
                print(f"  ADD  {field['field_label']} ({field_id}, seq {seq})")
                if not args.dry_run:
                    db.execute(
                        text(
                            """
                            INSERT INTO mst.data_capture_field
                                (field_id, template_id, field_sequence, field_name, field_label,
                                 field_type, unit_of_measure, is_mandatory)
                            VALUES
                                (:fid, :tid, :seq, :fname, :flabel, :ftype, :uom, false)
                            ON CONFLICT (field_id) DO NOTHING
                            """
                        ),
                        {
                            "fid": field_id,
                            "tid": template_id,
                            "seq": seq,
                            "fname": field["field_name"],
                            "flabel": field["field_label"],
                            "ftype": field["field_type"],
                            "uom": field.get("unit_of_measure"),
                        },
                    )

        if not args.dry_run:
            db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
