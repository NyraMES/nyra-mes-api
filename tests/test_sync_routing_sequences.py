"""Two-phase routing sequence updates must swap without unique collisions."""

from app.services.industry.activated_carbon.raw_material_types import (
    assign_operation_sequences,
    rebase_operation_sequences,
)


class _Row:
    def __init__(self, code, sequence):
        self.operation_code = code
        self.operation_sequence = sequence
        self.operation_seq = sequence


def test_rebase_moves_sequences_off_the_1_n_range():
    rows = [_Row("OP-A", 1), _Row("OP-B", 2), _Row("OP-C", 3)]
    rebase_operation_sequences(rows)
    assert [r.operation_sequence for r in rows] == [10000, 10001, 10002]
    assert [r.operation_seq for r in rows] == [10000, 10001, 10002]


def test_assign_after_rebase_can_swap_first_and_last():
    rows = [_Row("OP-A", 1), _Row("OP-B", 2), _Row("OP-C", 3)]
    by_code = {r.operation_code: r for r in rows}
    rebase_operation_sequences(by_code.values())
    assign_operation_sequences(by_code, {"OP-A": 3, "OP-B": 1, "OP-C": 2})
    assert by_code["OP-A"].operation_sequence == 3
    assert by_code["OP-B"].operation_sequence == 1
    assert by_code["OP-C"].operation_sequence == 2
    assert len({r.operation_sequence for r in rows}) == 3
