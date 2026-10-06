"""Printable nyra_mes_core structure reference — no row dumps.

Usage (repo root):
    python scripts/generate_mes_core_db_structure_pdf.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db.mes_core_database import get_mes_core_engine

OUT = ROOT / "docs" / "Nyra_MES_Core_DB_Structure_Reference.pdf"
SCHEMAS = ("core", "template", "mst", "trn", "exec", "qms", "kg", "ont")

TABLE_PURPOSE = {
    "core.tenant": "One row per plant / customer. GR Carbons is tenant_code GR_CARBONS.",
    "core.app_user": "Login identity (email, Cognito sub). Passwords are not stored here.",
    "core.user_tenant_access": "Which MES role a user has on a tenant (RMS, Activation, Admin, …).",
    "core.project_workspace": "Plant workspace inside a tenant. GR Carbons uses GR_CARBONS_ACTIVATED_CARBON.",
    "core.user_project_access": "Which role a user has on a workspace.",
    "core.capability": "Platform capability catalog (industry-agnostic).",
    "template.industry_template": "Industry packs (Activated Carbon, Automobile OEM).",
    "template.industry_capability": "Which capabilities each industry template turns on.",
    "template.raw_material_parameter_profile": "Shared AC raw-material QC / yield bands. Not a per-route table.",
    "mst.customer": "End customers. Also the buyer on inward (supplier receipt) POs.",
    "mst.supplier": "Raw-material vendors used on gate receipt.",
    "mst.product": "Finished / intermediate grades (FG-AC-*).",
    "mst.resource": "Kilns, rotaries, machines, labor, material resources.",
    "mst.equipment": "Physical equipment linked to a resource.",
    "mst.routing": "Process route for a product (AC standard process).",
    "mst.routing_operation": "Ordered steps on a route (kiln feed, destoning, screening, …).",
    "mst.routing_operation_parameter": "Per-operation capture parameters and limits.",
    "mst.operation_resource_requirement": "Which resource an operation needs.",
    "mst.sensor_device": "Kiln / plant sensor device register.",
    "mst.sensor_parameter": "Named parameters on a sensor device (temperature, etc.).",
    "mst.modbus_register_map": "Modbus register map for live kiln telemetry.",
    "mst.parameter_business_mapping": "Maps a sensor parameter to a business reading name.",
    "trn.customer_order": "Inward receipts (ORD-AC-*) and customer sales POs (CUST_PO_*). Shop-floor RM detail is in metadata.",
    "trn.customer_order_line": "Product + quantity lines on an inward or sales order.",
    "trn.production_order": "Internal PO created for the ontology when inward is received. Not shown on the shop floor.",
    "trn.production_lot": "Lot created for the ontology (LOT-AC-*). Kiln / destoning / post-activation detail is in metadata.",
    "trn.feasibility_check": "Feasibility header. The UI gate is skipped; rows may still exist for ontology.",
    "trn.feasibility_check_detail": "One line per feasibility check item.",
    "trn.dispatch": "Dispatch document against a customer sales PO.",
    "trn.sensor_reading": "One telemetry snapshot from a sensor device.",
    "trn.sensor_reading_value": "Individual values inside a telemetry snapshot.",
    "exec.operation_execution": "One shop-floor run of a routing step on a lot.",
    "exec.parameter_reading": "Numeric / text reading captured on an execution.",
    "qms.quality_check": "QC header for a lot (lab, destoning, kiln output, dispatch).",
    "qms.quality_result": "Measured characteristics for a QC header.",
    "kg.triple_store_staging": "Ontology triples: subject / predicate / object for inward and lot URIs.",
}

COLUMN_PURPOSE = {
    "tenant_id": "Which plant this row belongs to.",
    "workspace_id": "Which workspace / plant area this row belongs to.",
    "workspace_code": "Readable workspace code (GR_CARBONS_ACTIVATED_CARBON).",
    "metadata": "Flexible shop-floor notebook for this row. Not a separate file. See section 3.",
    "created_at": "When the row was created.",
    "updated_at": "When the row was last changed.",
    "status": "Business status of this row.",
    "is_active": "Whether this master / catalog row is still in use.",
    "industry_template_id": "Link to the industry pack.",
    "industry_template_code": "Industry pack code (ACTIVATED_CARBON).",
    "tenant_code": "Stable plant code (GR_CARBONS).",
    "tenant_name": "Display name of the plant.",
    "timezone": "Plant timezone.",
    "user_id": "Link to core.app_user.",
    "cognito_sub": "Cognito login identifier.",
    "email": "User login email.",
    "display_name": "Name shown in the UI.",
    "role_code": "MES role (MES_RMS, MES_Activation, MES_Admin, …).",
    "is_default": "Default tenant or workspace for this user.",
    "customer_id": "Link to mst.customer.",
    "customer_code": "Customer code.",
    "customer_name": "Customer display name.",
    "supplier_id": "Link to mst.supplier.",
    "supplier_code": "Supplier code.",
    "supplier_name": "Supplier display name.",
    "product_id": "Link to mst.product.",
    "product_code": "Product / grade code (FG-AC-*).",
    "product_name": "Product / grade name.",
    "product_type": "Product class (finished, raw, intermediate).",
    "uom": "Unit of measure (KG, EA).",
    "resource_id": "Link to mst.resource.",
    "resource_code": "Resource code (kiln, rotary, …).",
    "resource_name": "Resource display name.",
    "resource_type": "MACHINE, LABOR, TOOL, MATERIAL, WORKCELL, OTHER.",
    "equipment_id": "Link to mst.equipment.",
    "equipment_code": "Equipment code.",
    "equipment_name": "Equipment display name.",
    "equipment_type": "Equipment class.",
    "routing_id": "Link to mst.routing.",
    "routing_code": "Route code.",
    "routing_version": "Route version.",
    "process_family": "Family of the route (activation, inbound, …).",
    "routing_operation_id": "Link to one step on a route.",
    "operation_code": "Step code (IN-LAB, KILN-FEED, DESTONING, …).",
    "operation_sequence": "Order of the step on the route.",
    "operation_name": "Step display name.",
    "standard_cycle_min": "Standard cycle time in minutes.",
    "parameter_code": "Short code of a captured parameter.",
    "parameter_name": "Display name of a captured parameter.",
    "data_type": "Expected value type (number, text, …).",
    "unit": "Unit for the parameter.",
    "min_value": "Lower limit.",
    "max_value": "Upper limit.",
    "is_mandatory": "Whether the plant must fill this.",
    "quantity": "Quantity on this line.",
    "order_code": "Inward ORD-AC-* or sales CUST_PO_*.",
    "order_date": "Document date.",
    "order_id": "Link to trn.customer_order.",
    "customer_order_id": "Link to trn.customer_order.",
    "line_code": "Order line code.",
    "order_line_id": "Link to trn.customer_order_line.",
    "production_order_id": "Link to the internal production order.",
    "production_order_code": "Internal PO code (PO-AC-*). Hidden on the shop floor.",
    "planned_quantity": "Planned quantity on the internal PO.",
    "production_lot_id": "Link to the lot.",
    "lot_code": "Lot code (LOT-AC-*). Ontology identity; shop floor uses the inward order.",
    "lot_quantity": "Quantity on the lot.",
    "check_code": "Feasibility or QC document code.",
    "overall_status": "Feasibility result (PENDING, OK, BLOCKED, WAIVED).",
    "checked_at": "When feasibility was recorded.",
    "check_key": "Feasibility item key.",
    "check_label": "Feasibility item label.",
    "message": "Feasibility message.",
    "execution_id": "Link to exec.operation_execution.",
    "execution_code": "Shop-floor run code.",
    "started_at": "When the run started.",
    "completed_at": "When the run finished.",
    "reading_value": "Numeric reading.",
    "reading_text": "Text reading.",
    "recorded_at": "When the reading was taken.",
    "quality_check_id": "Link to qms.quality_check.",
    "check_type": "QC type (IN_PROCESS, DISPATCH, …).",
    "characteristic_code": "QC characteristic code.",
    "characteristic_name": "QC characteristic name.",
    "measured_value": "Numeric QC result.",
    "measured_text": "Text QC result.",
    "result_status": "PASS / FAIL / etc.",
    "finished_goods_lot_no": "Finished-goods lot shown on dispatch.",
    "grade": "Dispatched grade.",
    "bag_count": "Number of bags dispatched.",
    "total_weight": "Dispatched weight.",
    "vehicle_no": "Vehicle number.",
    "dispatch_date": "Dispatch date.",
    "invoice_ref": "Invoice reference.",
    "destination": "Ship-to destination.",
    "subject_uri": "Ontology subject, e.g. urn:nyra:ac:inward:ORD-AC-20.",
    "predicate_uri": "Ontology fact, e.g. lab approved, bag created, lot charged.",
    "object_uri": "Ontology object when it is another URI.",
    "object_literal": "Ontology object when it is a value (KG, bag code, status).",
    "object_datatype": "Literal datatype if used.",
    "source_table": "Which MES table produced this triple.",
    "source_id": "Source row id.",
    "export_status": "Whether the triple was exported from staging.",
    "raw_material_type": "Coconut shell, wood, etc.",
    "profile_code": "Parameter-profile code.",
    "profile_name": "Parameter-profile name.",
    "expected_yield_percent": "Expected yield for this material.",
    "device_id": "Sensor device id.",
    "device_code": "Sensor device code.",
    "register_address": "Modbus register address.",
}

TABLE_COLUMN_PURPOSE = {
    ("trn.customer_order", "status"): "OPEN, QC_PASSED, RELEASED, CLOSED, etc. Inward vs sales is also in metadata.flow.",
    ("trn.customer_order", "metadata"): "Gate receipt, lab, RMS bags, crusher, outward, release. See section 3.",
    ("trn.production_lot", "metadata"): "Kiln feed, destoning bags, post-activation bags, In Stock. See section 3.",
    ("trn.customer_order_line", "metadata"): "Line extras (grade, remaining qty) when used.",
    ("qms.quality_check", "metadata"): "Dispatch / bag QC header extras (vehicle, grade, lines).",
    ("qms.quality_result", "metadata"): "Per-characteristic extras or bag destinations.",
    ("mst.product", "metadata"): "Whether this product is a raw-material type, inbound operations, parameters.",
    ("mst.routing", "metadata"): "Route extras and industry flags.",
    ("mst.routing_operation", "metadata"): "process_step and whether the step is mandatory.",
    ("mst.resource", "metadata"): "In-use count and kiln / rotary extras.",
    ("core.tenant", "metadata"): "Tenant extras. Not shop-floor capture.",
}

METADATA_BLOCKS = [
    (
        "trn.customer_order — inward ORD-AC-*",
        [
            ["inward_receipt", "DC number, supplier KG, our KG from gate receipt."],
            ["initial_qc / inbound_execution.IN-LAB", "Lab moisture, dust, AD, approve or deny."],
            ["inward_bags", "RMS inward bags (RI_BAG_*), weight, fed-to-crusher status."],
            ["bag_reconciliation", "Bag total vs our inward weight."],
            ["inbound_execution.IN-RMS-BAG", "RMS inward step status and bag totals."],
            ["inbound_execution.IN-CRUSHER / crusher_output", "Rotary, mesh %, moisture, dust."],
            ["grade_separation / IN-RM-OUT", "Outward bags (RO_BAG_*), rotary, grade, KG."],
            ["released_lots", "Lots and KG released to production."],
            ["flow", "RAW_MATERIAL_INWARD for receipts."],
        ],
    ),
    (
        "trn.customer_order — sales CUST_PO_*",
        [
            ["flow", "CUSTOMER_SALES for a customer PO."],
            ["ordered_kg / dispatched_kg", "Ordered and already shipped weight."],
            ["product_id", "Grade the customer ordered."],
        ],
    ),
    (
        "trn.production_lot — LOT-AC-*",
        [
            ["source_inward_order_id", "Which inward the lot came from."],
            ["kiln_resource_code / kiln_loaded_kg", "Which kiln and how much was charged."],
            ["kiln_feed_events", "Each load: bag code, KG, time."],
            ["crusher_outward_bags", "RO bags attached when the lot was released."],
            ["destoning_output_bags", "Destoning bags, grade, destination, In Stock QC."],
            ["post-activation bag lists", "Screening / crushing / demagnetisation / blending bags."],
        ],
    ),
    (
        "kg.triple_store_staging",
        [
            ["subject_uri", "urn:nyra:ac:inward:{ORD-*} or urn:nyra:ac:lot:{LOT-*}. Do not replace."],
            ["predicate_uri", "The fact (received, lab approved, bag created, charged, dispatched)."],
            ["object_uri / object_literal", "The related thing or the value."],
        ],
    ),
]


def _esc(value: object) -> str:
    text_value = "" if value is None else str(value)
    return text_value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DocTitle",
            parent=base["Title"],
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#0f172a"),
            alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#0f766e"),
            spaceBefore=10,
            spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#155e75"),
            spaceBefore=8,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#334155"),
            spaceAfter=2,
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#0f172a"),
        ),
        "th": ParagraphStyle(
            "TH",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.white,
            fontName="Helvetica-Bold",
        ),
    }


def _table(headers, rows, styles, col_widths):
    head = [Paragraph(_esc(h), styles["th"]) for h in headers]
    body = [[Paragraph(_esc(c), styles["cell"]) for c in row] for row in rows]
    tbl = Table([head] + body, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.HexColor("#eef2ff")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tbl


def _page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#0f172a"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(14 * mm, 8 * mm, "Nyra MES Core — data structure reference  |  no row data")
    canvas.drawRightString(doc.pagesize[0] - 14 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _column_desc(fq: str, name: str) -> str:
    return TABLE_COLUMN_PURPOSE.get((fq, name)) or COLUMN_PURPOSE.get(name) or "Field stored on this table."


def main() -> int:
    engine = get_mes_core_engine()
    if engine is None:
        print("MES_CORE is not enabled")
        return 1

    styles = _styles()
    story = []
    now = datetime.now().strftime("%Y-%m-%d")
    page_width = A4[0] - 28 * mm

    with Session(bind=engine) as db:
        comments = {
            f"{r['schema_name']}.{r['table_name']}": r["comment"]
            for r in db.execute(
                text(
                    """
                    SELECT n.nspname AS schema_name, c.relname AS table_name, d.description AS comment
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    LEFT JOIN pg_description d ON d.objoid = c.oid AND d.objsubid = 0
                    WHERE n.nspname = ANY(:schemas) AND c.relkind = 'r'
                    """
                ),
                {"schemas": list(SCHEMAS)},
            ).mappings()
        }
        schema_comments = {
            r["schema_name"]: r["comment"]
            for r in db.execute(
                text(
                    """
                    SELECT n.nspname AS schema_name, d.description AS comment
                    FROM pg_namespace n
                    LEFT JOIN pg_description d ON d.objoid = n.oid
                    WHERE n.nspname = ANY(:schemas)
                    """
                ),
                {"schemas": list(SCHEMAS)},
            ).mappings()
        }

        insp = inspect(engine)
        tables: list[tuple[str, str]] = []
        for schema in SCHEMAS:
            try:
                names = insp.get_table_names(schema=schema)
            except Exception:
                continue
            for name in sorted(names):
                tables.append((schema, name))

        story.append(Paragraph("Nyra MES Core — data structure reference", styles["title"]))
        story.append(
            Paragraph(
                f"{now} · database postgres · nyra-mes-core · structure and meaning only. "
                "No live rows. Use this as a printed map of where data lives.",
                styles["body"],
            )
        )

        story.append(Paragraph("1. How the database is organised", styles["h1"]))
        story.append(
            Paragraph(
                "One PostgreSQL database holds every industry. Each plant is a <b>tenant</b>. "
                "GR Carbons is <b>GR_CARBONS</b>, workspace <b>GR_CARBONS_ACTIVATED_CARBON</b>. "
                "Shop-floor identity is the inward order <b>ORD-AC-*</b>. "
                "The system still creates a hidden PO and lot for the ontology.",
                styles["body"],
            )
        )
        schema_rows = []
        for schema in SCHEMAS:
            schema_rows.append(
                [
                    schema,
                    schema_comments.get(schema)
                    or {
                        "core": "Tenancy, users, workspaces.",
                        "template": "Industry packs and shared AC parameter bands.",
                        "mst": "Masters: customer, supplier, product, resource, route.",
                        "trn": "Orders, lots, dispatch, telemetry.",
                        "exec": "Shop-floor operation runs and readings.",
                        "qms": "Quality headers and results.",
                        "kg": "Triplet ontology staging.",
                        "ont": "Reserved for ontology class tables (empty at bootstrap).",
                    }.get(schema, ""),
                ]
            )
        story.append(_table(["Schema", "What it holds"], schema_rows, styles, [30 * mm, page_width - 30 * mm]))

        story.append(Paragraph("2. Table catalogue", styles["h1"]))
        cat_rows = []
        for schema, table in tables:
            fq = f"{schema}.{table}"
            cat_rows.append([fq, comments.get(fq) or TABLE_PURPOSE.get(fq, "See the table section below.")])
        story.append(_table(["Table", "What it stores"], cat_rows, styles, [58 * mm, page_width - 58 * mm]))

        story.append(PageBreak())
        story.append(Paragraph("3. The metadata JSON column — not a file", styles["h1"]))
        story.append(
            Paragraph(
                "There is no separate JSON file. Several tables have a column named <b>metadata</b>. "
                "That column is a notebook attached to the same row. "
                "Fixed columns hold identity (order code, lot code, status, product, quantity). "
                "The notebook holds the process the plant typed on the screens.",
                styles["body"],
            )
        )
        for title, rows in METADATA_BLOCKS:
            story.append(Paragraph(title, styles["h2"]))
            story.append(_table(["Key", "What it stores"], rows, styles, [62 * mm, page_width - 62 * mm]))

        story.append(PageBreak())
        story.append(Paragraph("4. Columns by table", styles["h1"]))
        story.append(
            Paragraph(
                "Print this section as the desk reference. "
                "PK = primary key. FK = link to another table.",
                styles["body"],
            )
        )

        for schema, table in tables:
            fq = f"{schema}.{table}"
            cols = insp.get_columns(table, schema=schema)
            pk = (insp.get_pk_constraint(table, schema=schema) or {}).get("constrained_columns") or []
            fk_cols: list[str] = []
            fk_labels = []
            for fk in insp.get_foreign_keys(table, schema=schema) or []:
                src_cols = list(fk.get("constrained_columns") or [])
                fk_cols.extend(src_cols)
                ref_schema = fk.get("referred_schema") or schema
                ref_table = fk.get("referred_table")
                fk_labels.append(f"{', '.join(src_cols)} → {ref_schema}.{ref_table}")
            story.append(Paragraph(fq, styles["h2"]))
            story.append(Paragraph(comments.get(fq) or TABLE_PURPOSE.get(fq, "Operational table."), styles["body"]))
            if pk:
                story.append(Paragraph(f"Primary key: {', '.join(pk)}.", styles["small"]))
            if fk_labels:
                story.append(Paragraph("Links: " + "; ".join(fk_labels) + ".", styles["small"]))
            col_rows = []
            for col in cols:
                flags = []
                if col["name"] in pk:
                    flags.append("PK")
                if col["name"] in fk_cols:
                    flags.append("FK")
                if not col.get("nullable", True):
                    flags.append("required")
                col_rows.append(
                    [
                        col["name"],
                        str(col.get("type") or ""),
                        ", ".join(flags) or "—",
                        _column_desc(fq, col["name"]),
                    ]
                )
            story.append(
                _table(
                    ["Column", "Type", "Key", "What it stores"],
                    col_rows,
                    styles,
                    [42 * mm, 38 * mm, 22 * mm, page_width - 102 * mm],
                )
            )
            story.append(Spacer(1, 6))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title="Nyra MES Core data structure reference",
        author="Nyra MES",
    )
    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
