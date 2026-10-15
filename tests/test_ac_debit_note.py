from decimal import Decimal

from app.services.industry.activated_carbon.debit_notes import evaluate_debit_note
from app.services.industry.activated_carbon.process_rules import default_process_rules


def _meta(*, our=500, supplier=500, moisture=15, lab="PASS", denied=False, note=None):
    return {
        "inward_receipt": {
            "our_weight_kg": str(our),
            "supplier_weight_kg": str(supplier),
        },
        "initial_qc": {"qc_status": lab, "moisture_pct": str(moisture)},
        "inbound_lab_denied": denied,
        **({"debit_note": note} if note else {}),
    }


def test_debit_note_not_eligible_when_weight_and_moisture_ok():
    result = evaluate_debit_note(_meta(), default_process_rules())
    assert result.lab_complete is True
    assert result.eligible is False
    assert result.reasons == []


def test_debit_note_eligible_when_weight_short():
    result = evaluate_debit_note(
        _meta(our=480, supplier=500),
        default_process_rules(),
        supplier_name="Greenfields Agro",
        supplier_code="SUP-AC-1",
    )
    assert result.eligible is True
    assert result.weight_short is True
    assert result.shortage_kg == Decimal("20")
    assert result.supplier_name == "Greenfields Agro"
    assert result.supplier_code == "SUP-AC-1"
    assert "weight_short" in result.reasons


def test_debit_note_eligible_when_moisture_high():
    result = evaluate_debit_note(_meta(moisture=24), default_process_rules())
    assert result.eligible is True
    assert result.moisture_high is True
    assert "moisture_high" in result.reasons


def test_debit_note_weight_short_waits_for_lab():
    pending = _meta(our=950, supplier=1000)
    pending["initial_qc"] = {}
    result = evaluate_debit_note(pending, default_process_rules())
    assert result.lab_complete is False
    assert result.eligible is False
    assert result.weight_short is True


def test_debit_note_moisture_only_waits_for_lab():
    pending = _meta(moisture=24)
    pending["initial_qc"] = {}
    result = evaluate_debit_note(pending, default_process_rules())
    assert result.eligible is False
    denied = _meta(our=400, moisture=30, lab="FAIL", denied=True)
    result = evaluate_debit_note(denied, default_process_rules())
    assert result.lab_complete is False
    assert result.eligible is False


def test_debit_note_falls_back_to_line_quantity_for_our_weight():
    meta = {
        "inward_receipt": {"supplier_weight_kg": "1000"},
        "initial_qc": {},
    }
    result = evaluate_debit_note(meta, default_process_rules(), our_weight_fallback=950)
    assert result.eligible is False
    assert result.weight_short is True
    assert result.our_weight_kg == Decimal("950")
    assert result.shortage_kg == Decimal("50")


def test_debit_note_already_raised_is_not_eligible_again():
    result = evaluate_debit_note(
        _meta(
            our=400,
            note={
                "debit_note_code": "DN-AC-1",
                "debit_note_value": "1500",
                "reasons": ["weight_short"],
                "raised_at": "2026-10-11T08:00:00+00:00",
                "raised_by": "rms@grcarbons",
            },
        ),
        default_process_rules(),
    )
    assert result.raised is True
    assert result.eligible is False
    assert result.debit_note_code == "DN-AC-1"
    assert result.raised_by == "rms@grcarbons"
