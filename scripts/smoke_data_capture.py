"""Smoke tests for process + data capture services."""

from app.db.database import SessionLocal
from app.services import data_capture_service


def main() -> None:
    db = SessionLocal()
    try:
        processes = data_capture_service.list_processes(db)
        print(f"processes: {len(processes)}")
        if processes:
            pid = processes[0].process_id
            form = data_capture_service.get_process_data_capture_form(db, pid)
            print(
                f"form for {pid}: templates={len(form.templates)} "
                f"fields={sum(len(t.fields) for t in form.templates)}"
            )

        from app.models.work_order import WorkOrder

        wo = (
            db.query(WorkOrder)
            .filter(WorkOrder.routing_operation_id.isnot(None))
            .first()
        )
        if wo:
            wform = data_capture_service.get_work_order_data_capture_form(
                db, wo.work_order_code
            )
            print(
                f"work order {wo.work_order_code}: process={wform.process_id} "
                f"templates={len(wform.templates)}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
