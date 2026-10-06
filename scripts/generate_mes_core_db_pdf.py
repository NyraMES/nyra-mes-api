"""Snapshot nyra_mes_core schema + GR_CARBONS data into a PDF.

Usage (repo root, venv with reportlab + existing MES deps):
    python scripts/generate_mes_core_db_pdf.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
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

OUT = ROOT / "docs" / "Nyra_MES_Core_DB_Structure_and_GR_Carbons_Data.pdf"
SCHEMAS = ("core", "template", "mst", "trn", "exec", "qms", "kg", "ont")
TENANT_CODE = "GR_CARBONS"
MAX_ROWS = 80
MAX_TRIPLES = 60
MAX_CELL = 220
REDACT_COLS = {
    "password",
    "password_hash",
    "secret",
    "secret_id",
    "api_key",
    "token",
    "access_token",
    "refresh_token",
}

TABLE_PURPOSE = {
    "template.industry_template": "Industry packs (Activated Carbon, Automobile OEM, …).",
    "template.industry_capability": "Which platform capabilities each industry template enables.",
    "template.raw_material_parameter_profile": "Shared AC raw-material QC / yield bands (not per-route).",
    "core.tenant": "Plant / customer tenancy. GR Carbons is tenant_code GR_CARBONS.",
    "core.app_user": "Login identities (Cognito email / sub). No passwords stored here.",
    "core.user_tenant_access": "User ↔ tenant role (MES_RMS, MES_Activation, MES_Admin, …).",
    "core.project_workspace": "Plant workspace. GR Carbons uses GR_CARBONS_ACTIVATED_CARBON.",
    "core.user_project_access": "User ↔ workspace role.",
    "core.capability": "Platform capability catalog.",
    "mst.customer": "End customers. Also used as the dummy buyer on inward (supplier receipt) POs.",
    "mst.supplier": "Raw-material vendors for gate receipt.",
    "mst.product": "Finished / intermediate grades (FG-AC-*).",
    "mst.resource": "Machines, rotaries, kilns, labor, material resources.",
    "mst.equipment": "Physical equipment linked to a resource.",
    "mst.routing": "Process route for a product (AC standard process).",
    "mst.routing_operation": "Ordered operations on a route (kiln feed, destoning, screening, …).",
    "mst.routing_operation_parameter": "Per-operation capture parameters and limits.",
    "mst.operation_resource_requirement": "Which resource an operation needs.",
    "trn.customer_order": "Inward receipts (ORD-AC-*) and customer sales POs (CUST_PO_*). Shop-floor RM state lives in metadata JSON.",
    "trn.customer_order_line": "Order lines (product + qty) for inward and sales.",
    "trn.production_order": "Internal PO created for ontology when inward is received (not shown on shop floor).",
    "trn.production_lot": "Lot created for ontology (LOT-AC-*). Activation / destoning / post-activation state is in metadata.",
    "trn.feasibility_check": "Feasibility header (UI gate is skipped; ontology rows may still exist).",
    "trn.feasibility_check_detail": "Per-check feasibility lines.",
    "trn.dispatch": "Dispatch documents against a customer sales PO.",
    "exec.operation_execution": "Shop-floor operation run for a lot + routing step.",
    "exec.parameter_reading": "Numeric / text readings captured on an execution.",
    "qms.quality_check": "QC header for a lot (lab, destoning bag QC, kiln output QC, dispatch QC).",
    "qms.quality_result": "QC characteristics; bag lists and destinations often sit in metadata JSON.",
    "kg.triple_store_staging": "Triplet ontology: subject / predicate / object for inward and lot URIs.",
}


def _short(value: Any, limit: int = MAX_CELL) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M") if value.tzinfo else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else str(value)
    if isinstance(value, UUID):
        return str(value)[:8]
    if isinstance(value, (dict, list)):
        text_value = json.dumps(value, default=str, ensure_ascii=True)
    else:
        text_value = str(value)
    text_value = text_value.replace("\n", " ").replace("\r", " ")
    if len(text_value) > limit:
        return text_value[: limit - 1] + "…"
    return text_value


def _esc(value: Any) -> str:
    text_value = _short(value)
    return (
        text_value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _styles():
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "DocTitle",
            parent=base["Title"],
            fontSize=16,
            leading=20,
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
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=3,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["Normal"],
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#334155"),
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base["Normal"],
            fontSize=6.5,
            leading=8,
            textColor=colors.HexColor("#0f172a"),
        ),
        "th": ParagraphStyle(
            "TH",
            parent=base["Normal"],
            fontSize=6.5,
            leading=8,
            textColor=colors.white,
            fontName="Helvetica-Bold",
        ),
    }
    return styles


def _table(headers: list[str], rows: list[list[Any]], styles, col_widths=None):
    head = [Paragraph(_esc(h), styles["th"]) for h in headers]
    body = [[Paragraph(_esc(c), styles["cell"]) for c in row] for row in rows]
    tbl = Table([head] + body, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.HexColor("#eef2ff")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return tbl


def _page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#0f172a"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(12 * mm, 7 * mm, "Nyra MES Core — confidential plant snapshot  |  GR_CARBONS")
    canvas.drawRightString(doc.pagesize[0] - 12 * mm, 7 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _list_tables(insp) -> list[tuple[str, str]]:
    found = []
    for schema in SCHEMAS:
        try:
            names = insp.get_table_names(schema=schema)
        except Exception:
            continue
        for name in sorted(names):
            found.append((schema, name))
    return found


def _columns(insp, schema: str, table: str) -> list[dict]:
    return insp.get_columns(table, schema=schema)


def _pk(insp, schema: str, table: str) -> list[str]:
    info = insp.get_pk_constraint(table, schema=schema) or {}
    return list(info.get("constrained_columns") or [])


def _fks(insp, schema: str, table: str) -> list[str]:
    items = []
    for fk in insp.get_foreign_keys(table, schema=schema) or []:
        cols = ", ".join(fk.get("constrained_columns") or [])
        ref_schema = fk.get("referred_schema") or schema
        ref_table = fk.get("referred_table")
        ref_cols = ", ".join(fk.get("referred_columns") or [])
        items.append(f"{cols} → {ref_schema}.{ref_table}({ref_cols})")
    return items


def _has_column(columns: list[dict], name: str) -> bool:
    return any(col["name"] == name for col in columns)


def _display_columns(columns: list[dict]) -> list[str]:
    names = [c["name"] for c in columns]
    hidden = {"tenant_id"}
    preferred = [
        "order_code",
        "lot_code",
        "production_order_code",
        "customer_code",
        "supplier_code",
        "product_code",
        "resource_code",
        "equipment_code",
        "routing_code",
        "operation_code",
        "check_code",
        "line_code",
        "workspace_code",
        "tenant_code",
        "template_code",
        "capability_code",
        "email",
        "display_name",
        "role_code",
        "status",
        "overall_status",
        "result_status",
        "subject_uri",
        "predicate_uri",
        "object_uri",
        "object_literal",
        "source_table",
        "customer_name",
        "supplier_name",
        "product_name",
        "resource_name",
        "operation_name",
        "grade",
        "quantity",
        "lot_quantity",
        "planned_quantity",
        "total_weight",
        "bag_count",
        "vehicle_no",
        "dispatch_date",
        "order_date",
        "created_at",
        "metadata",
    ]
    ordered = [n for n in preferred if n in names and n not in hidden]
    for name in names:
        if name in hidden or name in ordered:
            continue
        if name.endswith("_id") and len(ordered) >= 10:
            continue
        ordered.append(name)
        if len(ordered) >= 12:
            break
    return ordered or [n for n in names if n not in hidden][:10]


def _fetch_rows(db: Session, schema: str, table: str, columns: list[dict], tenant_id: str | None):
    col_names = [c["name"] for c in columns]
    qn = f'"{schema}"."{table}"'
    params: dict[str, Any] = {}
    where = ""
    limit = MAX_ROWS
    if table == "triple_store_staging":
        limit = MAX_TRIPLES
    if tenant_id and "tenant_id" in col_names:
        where = " WHERE tenant_id = :tid"
        params["tid"] = tenant_id
    elif schema == "core" and table == "app_user" and tenant_id:
        qn = "core.app_user"
        where = (
            " WHERE user_id IN (SELECT user_id FROM core.user_tenant_access WHERE tenant_id = :tid)"
        )
        params["tid"] = tenant_id
    count_sql = f"SELECT COUNT(*) FROM {qn}{where}"
    total = db.execute(text(count_sql), params).scalar() or 0
    order = "created_at DESC" if "created_at" in col_names else "1"
    data_sql = f"SELECT * FROM {qn}{where} ORDER BY {order} LIMIT {limit}"
    rows = db.execute(text(data_sql), params).mappings().all()
    return int(total), [dict(r) for r in rows]


def _redact_row(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if key.lower() in REDACT_COLS:
            out[key] = "[redacted]"
        else:
            out[key] = value
    return out


def main() -> int:
    engine = get_mes_core_engine()
    if engine is None:
        print("MES_CORE is not enabled")
        return 1

    styles = _styles()
    story: list[Any] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    with Session(bind=engine) as db:
        tenant = db.execute(
            text(
                """
                SELECT tenant_id, tenant_code, tenant_name, status, timezone
                FROM core.tenant
                WHERE tenant_code = :code
                """
            ),
            {"code": TENANT_CODE},
        ).mappings().first()
        if not tenant:
            print("GR_CARBONS tenant not found")
            return 1
        tenant_id = str(tenant["tenant_id"])

        workspace = db.execute(
            text(
                """
                SELECT workspace_code, workspace_name, status
                FROM core.project_workspace
                WHERE tenant_id = :tid
                ORDER BY workspace_code
                """
            ),
            {"tid": tenant_id},
        ).mappings().all()

        insp = inspect(engine)
        tables = _list_tables(insp)

        story.append(Paragraph("Nyra MES Core — database structure and stored data", styles["title"]))
        story.append(
            Paragraph(
                f"Snapshot {now} · database postgres on nyra-mes-core · tenant {TENANT_CODE} "
                f"({tenant['tenant_name']}) · transactional rows are GR Carbons only. "
                "Passwords and secrets are redacted. Large tables are capped.",
                styles["body"],
            )
        )
        story.append(Paragraph("1. How data is stored", styles["h1"]))
        story.append(
            Paragraph(
                "Nyra MES Core is one PostgreSQL database with schemas: "
                "<b>core</b> (tenancy), <b>template</b> (industry packs), <b>mst</b> (masters), "
                "<b>trn</b> (orders / lots / dispatch), <b>exec</b> (shop-floor runs), "
                "<b>qms</b> (quality), <b>kg</b> (triplet ontology). "
                "Activated Carbon shop-floor capture (gate receipt, lab, RMS bags, crusher, "
                "outward, kiln bags, destoning, post-activation destinations) is kept as "
                "<b>JSONB metadata</b> on inward orders, lots, and quality rows — not as extra tables. "
                "Triplet subjects stay <b>urn:nyra:ac:inward:{ORD-*}</b> and <b>urn:nyra:ac:lot:{LOT-*}</b>.",
                styles["body"],
            )
        )
        story.append(
            Paragraph(
                "Workspaces: "
                + (
                    ", ".join(f"{r['workspace_code']} ({r['status']})" for r in workspace)
                    or "none"
                )
                + ".",
                styles["body"],
            )
        )

        summary_rows = []
        table_payload = []
        for schema, table in tables:
            fq = f"{schema}.{table}"
            cols = _columns(insp, schema, table)
            total, rows = _fetch_rows(db, schema, table, cols, tenant_id)
            summary_rows.append(
                [
                    fq,
                    TABLE_PURPOSE.get(fq, "See columns below."),
                    str(total),
                    str(len(rows)),
                ]
            )
            table_payload.append((schema, table, cols, total, rows))

        story.append(Paragraph("2. Table catalogue (GR_CARBONS counts)", styles["h1"]))
        story.append(
            _table(
                ["Table", "What is stored", "Rows (scope)", "Shown"],
                summary_rows,
                styles,
                col_widths=[120, 380, 70, 50],
            )
        )

        story.append(PageBreak())
        story.append(Paragraph("3. Structure and data by table", styles["h1"]))

        page_width = landscape(A4)[0] - 24 * mm
        for schema, table, cols, total, rows in table_payload:
            fq = f"{schema}.{table}"
            block = []
            block.append(Paragraph(fq, styles["h2"]))
            block.append(Paragraph(TABLE_PURPOSE.get(fq, "Operational / catalog table."), styles["body"]))

            pk = _pk(insp, schema, table)
            fks = _fks(insp, schema, table)
            block.append(
                Paragraph(
                    f"Primary key: {', '.join(pk) or '—'}."
                    + (f" Foreign keys: {'; '.join(fks)}." if fks else ""),
                    styles["small"],
                )
            )

            col_rows = []
            for col in cols:
                col_type = str(col.get("type") or "")
                nullable = "YES" if col.get("nullable", True) else "NO"
                default = _short(col.get("default"), 40)
                col_rows.append([col["name"], col_type, nullable, default])
            block.append(_table(["Column", "Type", "Null", "Default"], col_rows, styles, col_widths=[160, 220, 50, 190]))
            block.append(Spacer(1, 4))

            if not rows:
                block.append(Paragraph(f"No rows in scope ({total} total in this filter).", styles["small"]))
            else:
                shown_cols = _display_columns(cols)
                data_rows = []
                for row in rows:
                    clean = _redact_row(row)
                    data_rows.append([clean.get(c) for c in shown_cols])
                col_w = page_width / max(len(shown_cols), 1)
                block.append(
                    Paragraph(
                        f"Data ({len(rows)} of {total} row(s) in GR_CARBONS / catalog scope):",
                        styles["small"],
                    )
                )
                block.append(_table(shown_cols, data_rows, styles, col_widths=[col_w] * len(shown_cols)))
                if total > len(rows):
                    block.append(
                        Paragraph(
                            f"{total - len(rows)} further row(s) omitted so the PDF stays readable.",
                            styles["small"],
                        )
                    )
            block.append(Spacer(1, 8))
            story.extend(block)

        if any(schema == "kg" and table == "triple_store_staging" for schema, table, *_ in table_payload):
            preds = db.execute(
                text(
                    """
                    SELECT predicate_uri, COUNT(*) AS n
                    FROM kg.triple_store_staging
                    WHERE tenant_id = :tid
                    GROUP BY predicate_uri
                    ORDER BY n DESC, predicate_uri
                    """
                ),
                {"tid": tenant_id},
            ).mappings().all()
            story.append(Paragraph("4. Triplet predicates in use (GR_CARBONS)", styles["h1"]))
            story.append(
                Paragraph(
                    "These are the ontology facts already written. Inward uses urn:nyra:ac:inward:{order}; "
                    "lots use urn:nyra:ac:lot:{lot}. Do not replace this store with a parallel capture model.",
                    styles["body"],
                )
            )
            if preds:
                story.append(
                    _table(
                        ["Predicate", "Count"],
                        [[r["predicate_uri"], r["n"]] for r in preds],
                        styles,
                        col_widths=[520, 80],
                    )
                )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title="Nyra MES Core DB structure and GR Carbons data",
        author="Nyra MES",
    )
    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
