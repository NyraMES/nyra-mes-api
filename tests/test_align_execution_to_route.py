from app.services.industry.activated_carbon.execution_enrich import align_operations_to_route


def test_execution_follows_master_route_order():
    route = [
        {"operation_code": "OP-KILN-FEED", "operation_sequence": 1, "operation_name": "Kiln", "process_step": "KILN_FEED"},
        {"operation_code": "OP-CRUSH-LOAD", "operation_sequence": 2, "operation_name": "Crush", "process_step": "GRINDING"},
    ]
    exec_ops = [
        {"operation_code": "OP-CRUSH-LOAD", "seq": 1, "status": "Ready", "work_order_id": "WO-2"},
        {"operation_code": "OP-KILN-FEED", "seq": 6, "status": "Ready", "work_order_id": "WO-1"},
    ]
    aligned = align_operations_to_route(route, exec_ops)
    assert [op["operation_code"] for op in aligned] == ["OP-KILN-FEED", "OP-CRUSH-LOAD"]
    assert [op["seq"] for op in aligned] == [1, 2]
    assert aligned[0]["can_start"] is True
    assert aligned[1]["can_start"] is False


def test_new_master_step_appears_before_work_order_exists():
    route = [
        {"operation_code": "OP-A", "operation_sequence": 1, "operation_name": "A"},
        {"operation_code": "OP-NEW", "operation_sequence": 2, "operation_name": "New step"},
    ]
    exec_ops = [{"operation_code": "OP-A", "status": "Completed", "work_order_id": "WO-A"}]
    aligned = align_operations_to_route(route, exec_ops)
    assert aligned[1]["operation_name"] == "New step"
    assert aligned[1]["status"] == "Pending"
    assert aligned[1]["can_start"] is False
