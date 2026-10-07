"""PDF of GR Carbons / Activated Carbon PostgreSQL business-code sequences.

Usage (repo root):
    python scripts/generate_ac_sequences_pdf.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import text

load_dotenv(ROOT / ".env")

from app.db.mes_core_database import get_mes_core_engine

OUT = ROOT / "docs" / "GR_Carbons_Business_Code_Sequences.pdf"

NAVY = colors.HexColor("#0D3A6E")
INK = colors.HexColor("#0f172a")
GRID = colors.HexColor("#cbd5e1")
ROW_A = colors.HexColor("#f8fafc")
ROW_B = colors.HexColor("#e8eef6")

# Sequence, generated key, what it is used for, dedicated vs shared
SEQUENCE_CATALOG = [
    ("core.customer_code_seq", "CUST-AC-*", "Customer master", "Shared with other MES tenants"),
    ("core.supplier_code_seq", "SUP-AC-*", "Supplier master", "Shared with other MES tenants"),
    ("core.product_code_seq", "RAW-AC-* and FG-AC-*", "Raw and finished product masters", "Shared — RAW and FG use this one sequence"),
    ("core.resource_code_seq", "RES-*", "Kilns, rotaries, machines", "Shared with other MES tenants"),
    ("core.equipment_code_seq", "EQ-*", "Equipment linked to a resource", "Shared with other MES tenants"),
    ("core.routing_code_seq", "RT-AC-*", "Process routing", "Shared with other MES tenants"),
    ("core.routing_operation_code_seq", "OP-*", "Routing operation code", "Shared with other MES tenants"),
    ("core.customer_order_code_seq", "ORD-AC-*", "Gate receipt / inward identity", "Shared with other MES tenants"),
    ("core.customer_order_line_code_seq", "ORDL-AC-*", "Inward / sales order line", "Shared with other MES tenants"),
    ("core.ac_customer_po_seq", "CUST_PO_*", "Customer sales PO", "Dedicated"),
    ("core.production_order_code_seq", "PO-AC-*", "Ontology production order (hidden on shop floor)", "Shared with other MES tenants"),
    ("core.lot_code_seq", "LOT-AC-*", "Ontology production lot (hidden on shop floor)", "Shared with other MES tenants"),
    ("core.feasibility_check_code_seq", "FEAS*", "Feasibility check (gate skipped in UI)", "Shared with other MES tenants"),
    ("core.execution_code_seq", "EXEC-AC-*", "Shop-floor operation execution", "Shared with other MES tenants"),
    ("core.schedule_code_seq", "SCH*", "Schedule header", "Shared with other MES tenants"),
    ("core.quality_check_code_seq", "QC-AC-*", "Quality check header", "Shared with other MES tenants"),
    ("core.ncr_code_seq", "NCR*", "Non-conformance", "Shared with other MES tenants"),
    ("core.dispatch_code_seq", "DISP-AC-*", "Dispatch document", "Shared with other MES tenants"),
    ("core.ac_bag_ri_seq", "RI_BAG_*", "RMS inward bags", "Dedicated"),
    ("core.ac_bag_ro_seq", "RO_BAG_*", "RMS outward bags", "Dedicated"),
    ("core.ac_kiln_out_ka_seq", "KA_DDMMYY_*", "Kiln A output bags", "Dedicated"),
    ("core.ac_kiln_out_kb_seq", "KB_DDMMYY_*", "Kiln B output bags", "Dedicated"),
    ("core.ac_deston_ds_seq", "DS_DDMMYY_*", "Destoning bags", "Dedicated"),
    ("core.ac_post_sc_seq", "SC_DDMMYY_*", "Screening bags", "Dedicated"),
    ("core.ac_post_dd_seq", "DD_DDMMYY_*", "De-dusting bags", "Dedicated"),
    ("core.ac_post_cr_seq", "CR_DDMMYY_*", "Crushing bags", "Dedicated"),
    ("core.ac_post_dm_seq", "DM_DDMMYY_*", "De-magnetisation bags", "Dedicated"),
    ("core.ac_post_bl_seq", "BL_DDMMYY_*", "Blending bags", "Dedicated"),
    ("core.ac_post_fg_seq", "FG_DDMMYY_*", "Finished-goods bags", "Dedicated"),
]


def _esc(value: object) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DocTitle", parent=base["Title"], fontSize=16, leading=20,
            textColor=NAVY, alignment=TA_LEFT, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=9, leading=12,
            textColor=INK, spaceAfter=4,
        ),
        "cell": ParagraphStyle(
            "Cell", parent=base["Normal"], fontSize=8, leading=10.5, textColor=INK,
        ),
        "th": ParagraphStyle(
            "TH", parent=base["Normal"], fontSize=8, leading=10,
            textColor=colors.white, fontName="Helvetica-Bold",
        ),
    }


def _table(headers, rows, styles, col_widths):
    head = [Paragraph(_esc(h), styles["th"]) for h in headers]
    body = [[Paragraph(_esc(c), styles["cell"]) for c in row] for row in rows]
    tbl = Table([head] + body, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [ROW_A, ROW_B]),
                ("GRID", (0, 0), (-1, -1), 0.25, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tbl


def _page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, doc.pagesize[0], 10 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(12 * mm, 4 * mm, "GR Carbons  |  Business-code sequences")
    canvas.drawRightString(doc.pagesize[0] - 12 * mm, 4 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _live_next_values() -> dict[str, str]:
    engine = get_mes_core_engine()
    if engine is None:
        return {}
    out: dict[str, str] = {}
    with engine.connect() as conn:
        names = conn.execute(
            text(
                """
                SELECT n.nspname, c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'S' AND n.nspname = 'core'
                """
            )
        ).fetchall()
        for schema, name in names:
            fq = f"{schema}.{name}"
            last, called = conn.execute(
                text(f"SELECT last_value, is_called FROM {fq}")
            ).fetchone()
            nxt = int(last or 1) if not called else int(last or 0) + 1
            out[fq] = str(nxt)
    return out


def main() -> int:
    styles = _styles()
    page = landscape(A4)
    usable = page[0] - 24 * mm
    now = datetime.now().strftime("%Y-%m-%d")
    live = _live_next_values()

    rows = []
    for seq, key, used_for, dedicated in SEQUENCE_CATALOG:
        rows.append([seq, key, used_for, dedicated, live.get(seq, "not created yet")])

    story = [
        Paragraph("GR Carbons — Business-code sequences", styles["title"]),
        Paragraph(
            f"{now} · PostgreSQL sequences in schema core. "
            "Each generated key takes its number from nextval of the named sequence. "
            "Dedicated sequences belong to Activated Carbon shop-floor bags / customer PO. "
            "Shared sequences also serve other MES tenants on the same database.",
            styles["body"],
        ),
        Paragraph(
            "RAW-AC-* and FG-AC-* share core.product_code_seq. "
            "Shop-floor bag sequences are created on first use. "
            "Next value is the number the next new key will receive.",
            styles["body"],
        ),
        Spacer(1, 4),
        _table(
            ["Sequence name", "Generated key", "Used for", "Dedicated / shared", "Next value"],
            rows,
            styles,
            [58 * mm, 42 * mm, 70 * mm, 52 * mm, usable - 222 * mm],
        ),
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=page,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title="GR Carbons Business-code sequences",
        author="Nyra MES",
    )
    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
