"""
Seed GR Carbons coconut-shell process from numbered notebook pages 1–4.

Canonical *time* order (page numbers 2–4 are not read 2→3→4 on the floor):
  Page 1 — Receivables: gate receipt (UI Inward tab) → Lab → RMS inward →
            crusher performance → RM outward  [inbound_operations]
  Fixed UI — Release to Production (PO + LOT-AC-*; RM QC not required)
  Page 4 — §2 crushing → §3 de-dusting → §4 de-magnetisation → §5 blending
  Page 2 — §1 kiln feed bag QC → §2 kiln feed → §3 kiln output QC → §4 kiln telemetry
  Page 3 — §5 destoning → §6 destoning bag QC → Post-activation §1 screening
  Last shop step — finished-goods QC (after all Page 4 pre-kiln, Page 2 kiln, Page 3 post-activation)
           → in stock

Does not change triplet URI constants — parameters use captures on
urn:nyra:ac:inward:{order_code} and urn:nyra:ac:lot:{lot_code} templates.

Usage (venv, .env):
  python scripts/seed_gr_carbons_process_flow.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.core.exceptions import NotFoundError
from app.core.tenant_context import resolve_tenant
from app.db.mes_core_database import get_mes_core_engine
from app.models.mes_core import Product
from app.schemas.mes_core.schemas import (
    AcRawMaterialProcessParameter,
    AcRawMaterialTypeOperation,
    AcRawMaterialTypeUpdate,
)
from app.services.industry.activated_carbon import raw_material_types as rmt
from app.services.mes_core.base import TenantRepository
from sqlalchemy.orm import Session

TENANT = os.getenv("AC_TENANT_CODE", "GR_CARBONS")
WORKSPACE = os.getenv("AC_WORKSPACE_CODE", "GR_CARBONS_ACTIVATED_CARBON")
RAW_CODE = "RAW-COCO-SHELL"
FINISHED_NAME = "GR Granular Activated Carbon"


def _param(
    key: str,
    label: str,
    *,
    unit: str = "",
    process_step: str,
    used_at: str = "execution",
    mandatory: bool = False,
    subject: str = "urn:nyra:ac:lot:{lot_code}",
    operation_code: str | None = None,
    string_field: bool = False,
) -> AcRawMaterialProcessParameter:
    if string_field or (not unit and not string_field):
        od = "http://www.w3.org/2001/XMLSchema#string"
    else:
        od = "http://www.w3.org/2001/XMLSchema#decimal"
    return AcRawMaterialProcessParameter(
        key=key,
        label=label,
        unit=unit or None,
        process_step=process_step,
        used_at=used_at,
        mandatory=mandatory,
        operation_code=operation_code,
        ontology_predicate="captures",
        subject_uri_template=subject,
        object_datatype=od,
    )


def _mesh_kg_params(
    prefix: str,
    sizes: list[str],
    *,
    process_step: str,
    subject: str,
    used_at: str = "execution",
    operation_code: str | None = None,
) -> list[AcRawMaterialProcessParameter]:
    out: list[AcRawMaterialProcessParameter] = []
    for size in sizes:
        slug = (
            size.replace("/", "_")
            .replace("+", "plus_")
            .replace("-", "minus_")
            .replace("x", "x")
            .lower()
        )
        key = f"{prefix}_{slug}_kg"
        out.append(
            _param(
                key,
                f"{size} (kg)",
                unit="KG",
                process_step=process_step,
                used_at=used_at,
                subject=subject,
                operation_code=operation_code,
            )
        )
    return out


def _op(seq: int, code: str, name: str, step: str, mandatory: bool = True) -> AcRawMaterialTypeOperation:
    return AcRawMaterialTypeOperation(
        operation_sequence=seq,
        operation_code=code,
        operation_name=name,
        process_step=step,
        is_mandatory=mandatory,
    )


def build_gr_process() -> tuple[list[AcRawMaterialTypeOperation], list[AcRawMaterialTypeOperation], list]:
    """Page 1: Receivables (after gate inward) + RMS — then release (no RM QC)."""
    inbound = [
        _op(1, "IN-LAB", "Lab — moisture, dust, AD (approve/deny)", "SCREENING"),
        _op(2, "IN-RMS-BAG", "RMS inward — bag & weight", "PACKING"),
        _op(3, "IN-CRUSHER", "Crusher performance — rotary & mesh sizes", "CRUSHING"),
        _op(4, "IN-RM-OUT", "RM outward — grade splits & bag weight", "SCREENING"),
    ]

    inward_subject = "urn:nyra:ac:inward:{order_code}"
    inbound_params = [
        _param(
            "dc_number",
            "Supplier DC number",
            process_step="RAW_MATERIAL_INWARD",
            used_at="inward",
            subject=inward_subject,
            string_field=True,
        ),
        _param(
            "supplier_weight_kg",
            "Supplier weight",
            unit="KG",
            process_step="RAW_MATERIAL_INWARD",
            used_at="inward",
            subject=inward_subject,
        ),
        _param(
            "supplier_value_inr",
            "Supplier value (INR)",
            unit="INR",
            process_step="RAW_MATERIAL_INWARD",
            used_at="inward",
            subject=inward_subject,
        ),
        _param(
            "our_value_inr",
            "Our assessed value (INR)",
            unit="INR",
            process_step="RAW_MATERIAL_INWARD",
            used_at="inward",
            subject=inward_subject,
        ),
        _param(
            "our_weight_kg",
            "Our weight",
            unit="KG",
            process_step="RAW_MATERIAL_INWARD",
            used_at="inward",
            subject=inward_subject,
        ),
        _param(
            "received_qty_kg",
            "Quantity received",
            unit="KG",
            process_step="RAW_MATERIAL_INWARD",
            used_at="inward",
            subject=inward_subject,
        ),
        _param(
            "moisture_pct",
            "Moisture",
            unit="%",
            process_step="SCREENING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-LAB",
        ),
        _param(
            "dust_pct",
            "Dust",
            unit="%",
            process_step="SCREENING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-LAB",
        ),
        _param(
            "ad_value",
            "AD value",
            process_step="SCREENING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-LAB",
            string_field=True,
        ),
        _param(
            "qc_decision",
            "Approve / deny",
            process_step="SCREENING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-LAB",
            string_field=True,
        ),
        _param(
            "lab_remarks",
            "Lab remarks",
            process_step="SCREENING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-LAB",
            string_field=True,
        ),
        _param(
            "bag_weight_kg",
            "Bag weight",
            unit="KG",
            process_step="PACKING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-RMS-BAG",
        ),
        _param(
            "inward_bag_code",
            "Bag reference",
            process_step="PACKING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-RMS-BAG",
            string_field=True,
        ),
        _param(
            "rotary",
            "Rotary",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
            string_field=True,
        ),
        _param(
            "crusher_grade",
            "Crusher grade",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
            string_field=True,
        ),
        _param(
            "moisture_after_crush_pct",
            "Moisture after crush",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "dust_generation_pct",
            "Dust generated",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "crusher_remarks",
            "Crusher remarks",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
            string_field=True,
        ),
        _param(
            "moisture_pct",
            "Moisture",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "dust_pct",
            "Dust",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "mesh_plus_2_pct",
            "+2",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "mesh_2_3_pct",
            "2/3",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "mesh_3_4_pct",
            "3/4",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "mesh_4_6_pct",
            "4/6",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "mesh_6_10_pct",
            "6/10",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "mesh_10_12_pct",
            "10/12",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "mesh_12_14_pct",
            "12/14",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "mesh_minus_14_pct",
            "-14",
            unit="%",
            process_step="CRUSHING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-CRUSHER",
        ),
        _param(
            "rm_out_grade",
            "RM outward grade",
            process_step="SCREENING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-RM-OUT",
            string_field=True,
        ),
        _param(
            "separation_grade_kg",
            "RM outward bag weight",
            unit="KG",
            process_step="SCREENING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-RM-OUT",
        ),
        _param(
            "rm_out_remarks",
            "RM outward remarks",
            process_step="SCREENING",
            used_at="inbound",
            subject=inward_subject,
            operation_code="IN-RM-OUT",
            string_field=True,
        ),
    ]

    """After release: Page 4 pre-kiln → Page 2 activation → Page 3 destoning & post-activation."""
    shop = [
        _op(1, "OP-CRUSH-LOAD", "P4-2 Crushing — input bag → crusher output grade", "GRINDING"),
        _op(2, "OP-DEDUST", "P4-3 De-dusting — screening bin → de-duster, grade & wt", "DRYING"),
        _op(3, "OP-DEMAG", "P4-4 De-magnetisation — bag load → grade out", "GRINDING"),
        _op(4, "OP-BLEND", "P4-5 Blending — bag load → output grade", "GRADE_SEPARATION"),
        _op(5, "OP-KILN-FEED-QC", "P2-1 Kiln feed bag quality (+2…-14, moisture, dust, volatile)", "KILN_FEED"),
        _op(6, "OP-KILN-FEED", "P2-2 Kiln feed — load bag & charge weight", "KILN_FEED"),
        _op(7, "OP-KILN-OUT-QC", "P2-3 Kiln output quality (+3…-30, CBD, etc.)", "ACTIVATION"),
        _op(8, "OP-KILN-TEMP", "P2-4 Kiln temperature & telemetry (T1–T4, RPM, dampers, steam)", "ACTIVATION"),
        _op(9, "OP-DESTONING", "P3-5 Destoning — kiln O/P bag → destoning loader", "DESTONING"),
        _op(10, "OP-DESTON-QC", "P3-6 Destoning bag quality (+3…-30, CBD, etc.)", "SCREENING"),
        _op(11, "OP-POST-SCREEN", "P3 Post-activation screening (+4, 4x6, 6x8, -8, MBD, CBD)", "SCREENING"),
        _op(12, "OP-FG-QC", "Final — finished goods QC (after post-activation screening)", "QC"),
    ]

    lot = "urn:nyra:ac:lot:{lot_code}"
    shop_params = [
        _param(
            "shop_crush_output_kg",
            "Crushing output mass",
            unit="KG",
            process_step="GRINDING",
            subject=lot,
            operation_code="OP-CRUSH-LOAD",
        ),
        _param(
            "shop_crush_grade",
            "Crushing output grade",
            process_step="GRINDING",
            subject=lot,
            operation_code="OP-CRUSH-LOAD",
            string_field=True,
        ),
        _param(
            "shop_crush_remarks",
            "Crushing remarks",
            process_step="GRINDING",
            subject=lot,
            operation_code="OP-CRUSH-LOAD",
            string_field=True,
        ),
        _param(
            "shop_dedust_output_kg",
            "De-dusting output mass",
            unit="KG",
            process_step="DRYING",
            subject=lot,
            operation_code="OP-DEDUST",
        ),
        _param(
            "shop_dedust_grade",
            "De-dusting output grade",
            process_step="DRYING",
            subject=lot,
            operation_code="OP-DEDUST",
            string_field=True,
        ),
        _param(
            "shop_demag_output_kg",
            "De-mag output mass",
            unit="KG",
            process_step="GRINDING",
            subject=lot,
            operation_code="OP-DEMAG",
        ),
        _param(
            "shop_demag_grade",
            "De-mag output grade",
            process_step="GRINDING",
            subject=lot,
            operation_code="OP-DEMAG",
            string_field=True,
        ),
        _param(
            "shop_blend_output_kg",
            "Blend output mass",
            unit="KG",
            process_step="GRADE_SEPARATION",
            subject=lot,
            operation_code="OP-BLEND",
        ),
        _param(
            "shop_blend_grade",
            "Blend output grade",
            process_step="GRADE_SEPARATION",
            subject=lot,
            operation_code="OP-BLEND",
            string_field=True,
        ),
        *_mesh_kg_params(
            "kfqc",
            ["+2", "2/3", "3/6", "6/8", "8/10", "10/12", "12/14", "-14"],
            process_step="KILN_FEED",
            subject=lot,
            operation_code="OP-KILN-FEED-QC",
        ),
        _param("feed_moisture_pct", "Feed moisture", unit="%", process_step="KILN_FEED", subject=lot, operation_code="OP-KILN-FEED-QC"),
        _param("feed_dust_pct", "Feed dust", unit="%", process_step="KILN_FEED", subject=lot, operation_code="OP-KILN-FEED-QC"),
        _param("feed_volatile_pct", "Feed volatile", unit="%", process_step="KILN_FEED", subject=lot, operation_code="OP-KILN-FEED-QC"),
        _param("kfqc_remarks", "Kiln feed QC remarks", process_step="KILN_FEED", subject=lot, operation_code="OP-KILN-FEED-QC", string_field=True),
        _param("charge_kg", "Kiln charge weight", unit="KG", process_step="KILN_FEED", mandatory=True, subject=lot, operation_code="OP-KILN-FEED"),
        _param("kiln_feed_bag_ref", "Kiln feed bag load", process_step="KILN_FEED", subject=lot, operation_code="OP-KILN-FEED", string_field=True),
        *_mesh_kg_params(
            "kiln_out",
            ["+3", "3/4", "4/8", "8/12", "12/30", "-30"],
            process_step="ACTIVATION",
            subject=lot,
            operation_code="OP-KILN-OUT-QC",
        ),
        _param("kiln_out_cbd", "Kiln output CBD", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-OUT-QC", string_field=True),
        _param("kiln_out_remarks", "Kiln output QC remarks", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-OUT-QC", string_field=True),
        _param("telemetry_date", "Telemetry date", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP", string_field=True),
        _param("kiln_id", "Kiln", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP", string_field=True),
        _param("kiln_temp_t1_c", "Kiln T1", unit="°C", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP"),
        _param("kiln_temp_t2_c", "Kiln T2", unit="°C", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP"),
        _param("kiln_temp_t3_c", "Kiln T3", unit="°C", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP"),
        _param("kiln_temp_t4_c", "Kiln T4", unit="°C", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP"),
        _param("chamber_value", "Chamber value", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP", string_field=True),
        _param("kiln_feed_rate", "Feed rate", unit="kg/h", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP"),
        _param("kiln_rpm", "Kiln RPM", unit="rpm", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP"),
        _param("main_damper_pct", "Main damper open", unit="%", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP"),
        _param("boiler_damper_pct", "Boiler damper open", unit="%", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP"),
        _param("steam_pressure_psi", "Steam pressure", unit="PSI", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP"),
        _param("telemetry_remarks", "Telemetry remarks", process_step="ACTIVATION", subject=lot, operation_code="OP-KILN-TEMP", string_field=True),
        _param("stone_removed_kg", "Stones / grit removed", unit="KG", process_step="DESTONING", subject=lot, operation_code="OP-DESTONING"),
        _param("destoning_bag_ref", "Destoning output bag", process_step="DESTONING", subject=lot, operation_code="OP-DESTONING", string_field=True),
        *_mesh_kg_params(
            "deston_qc",
            ["+3", "3/4", "4/8", "8/12", "12/30", "-30"],
            process_step="SCREENING",
            subject=lot,
            operation_code="OP-DESTON-QC",
        ),
        _param("deston_qc_cbd", "Destoning bag CBD", process_step="SCREENING", subject=lot, operation_code="OP-DESTON-QC", string_field=True),
        _param("deston_qc_remarks", "Destoning QC remarks", process_step="SCREENING", subject=lot, operation_code="OP-DESTON-QC", string_field=True),
        *_mesh_kg_params(
            "post_scr",
            ["+4", "4x6", "6x8", "-8"],
            process_step="SCREENING",
            subject=lot,
            operation_code="OP-POST-SCREEN",
        ),
        _param("post_scr_mbd", "Post-activation MBD", process_step="SCREENING", subject=lot, operation_code="OP-POST-SCREEN", string_field=True),
        _param("post_scr_cbd", "Post-activation CBD", process_step="SCREENING", subject=lot, operation_code="OP-POST-SCREEN", string_field=True),
        _param("post_scr_moisture_pct", "Post-activation moisture", unit="%", process_step="SCREENING", subject=lot, operation_code="OP-POST-SCREEN"),
        _param("post_scr_instock", "Mark in stock", process_step="SCREENING", subject=lot, operation_code="OP-POST-SCREEN", string_field=True),
        _param("good_kg", "Good fraction (screening)", unit="KG", process_step="SCREENING", subject=lot, operation_code="OP-POST-SCREEN"),
        _param("iodine_mg_g", "Iodine number", unit="mg/g", process_step="QC", subject=lot, operation_code="OP-FG-QC"),
        _param("fg_qc_remarks", "Finished goods QC remarks", process_step="QC", subject=lot, operation_code="OP-FG-QC", string_field=True),
    ]

    return inbound, shop, inbound_params + shop_params


def main() -> int:
    engine = get_mes_core_engine()
    if not engine:
        print("ERROR: MES_CORE not enabled")
        return 1

    db = Session(bind=engine)
    try:
        tenant = resolve_tenant(db, TENANT, WORKSPACE)
        repo = TenantRepository(db, tenant)
        raw = repo.get_by_code(Product, Product.product_code, RAW_CODE)
    except NotFoundError:
        print(f"ERROR: Raw product {RAW_CODE} not found — run reset with --install-master first")
        return 1

    inbound, shop, params = build_gr_process()
    payload = AcRawMaterialTypeUpdate(
        product_name="Coconut Shell (GR)",
        finished_product_name=FINISHED_NAME,
        inbound_operations=inbound,
        operations=shop,
        process_parameters=params,
    )

    row = rmt.update_raw_material_type(db, tenant, raw.product_id, payload)
    from app.services.industry.activated_carbon import inbound_admin as ac_inbound_admin

    admin = ac_inbound_admin.save_inbound_admin(
        db, tenant, ac_inbound_admin.default_inbound_admin()
    )
    db.commit()

    print("OK: GR Carbons process seeded on", row.product_code, row.product_name)
    print(f"  routing: {row.routing_code}")
    print(f"  inbound prep steps: {len(row.inbound_operations)}")
    print(f"  shop-floor steps: {len(row.operations)}")
    print(f"  triplet parameters: {len(row.process_parameters)}")
    print("  Ontology URIs unchanged — parameters use captures on inward/lot subjects.")
    print(f"  admin rotaries: {len(admin['rotaries'])}")
    print(f"  admin outward splits: {len(admin['outward_splits'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
