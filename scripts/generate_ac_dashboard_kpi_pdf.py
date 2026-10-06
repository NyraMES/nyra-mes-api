"""Dashboard KPI calculation reference for GR Carbons.

Usage (repo root):
    python scripts/generate_ac_dashboard_kpi_pdf.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "GR_Carbons_Dashboard_KPI_Calculations.pdf"

NAVY = colors.HexColor("#0D3A6E")
INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#334155")
GRID = colors.HexColor("#cbd5e1")
ROW_A = colors.HexColor("#f8fafc")
ROW_B = colors.HexColor("#e8eef6")


def _esc(value: object) -> str:
    text_value = "" if value is None else str(value)
    return text_value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DocTitle",
            parent=base["Title"],
            fontSize=16,
            leading=20,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontSize=11,
            leading=14,
            textColor=NAVY,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
            textColor=INK,
            spaceAfter=4,
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base["Normal"],
            fontSize=8,
            leading=10.5,
            textColor=INK,
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
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [ROW_A, ROW_B]),
                ("GRID", (0, 0), (-1, -1), 0.25, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
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
    canvas.drawString(12 * mm, 4 * mm, "GR Carbons  |  Dashboard KPI calculations  |  current live logic")
    canvas.drawRightString(doc.pagesize[0] - 12 * mm, 4 * mm, f"Page {doc.page}")
    canvas.restoreState()


KPI_ROWS = [
    [
        "Charcoal stock\n(Charcoal data)",
        "Raw charcoal still at the dock — received, not yet released to production.",
        "pending_kg = inward our-weight (ordered_kg) − allocated_to_production_kg",
        "Inward orders (ORD-AC-*) with raw-material lines. KPI uses pending_kg. Chart uses each inward remaining available kg, stacked by supplier and material.",
        "Does not include released lots. Chart and KPI can differ slightly if available kg and pending kg are not in sync.",
    ],
    [
        "GC\n(GCharcoal stock)",
        "Released charcoal waiting to be loaded on a kiln.",
        "Sum of lot_quantity for lots with status CREATED",
        "Production lots created at Release to Production. Chart groups those lots by supplier and kiln.",
        "GC is GCharcoal, not a carbon-number grade. Once the lot is loaded, it leaves GC and moves to Exklin with stone.",
    ],
    [
        "Plant yield",
        "Plant-wide conversion of raw charged to finished output.",
        "finished output kg ÷ raw charged kg × 100",
        "Numerator: STOCKED lot kg + DISPATCHED last_dispatch_kg. Fallback: In Stock / finished-goods kg + all dispatch kg. Denominator: allocated_to_production_kg. Fallback: last_release_kg on the production order, then planned order qty.",
        "Target on the gauge is 22%. Stays blank while material is only WIP (nothing stocked or dispatched). One plant number — not per lot on the card.",
    ],
    [
        "Production availability",
        "Share of the active book that is currently running.",
        "max(lots IN_PROGRESS, kilns RUNNING) ÷ active lots × 100",
        "Active lots = lots not DISPATCHED / CLOSED / CANCELLED (or the dashboard active-order list). A kiln is RUNNING when an IN_PROGRESS lot is on it (IN_KILN, kiln feed, or activation).",
        "Not equipment uptime or OEE. If there are no active lots, it uses kilns running ÷ kiln count. Target is 90%.",
    ],
    [
        "Material Flow (WIP)",
        "Total kilograms sitting in the five stock stages.",
        "Charcoal + GC + Exklin with stone + Exklin without stone + Final grade",
        "Same five buckets shown on the Material Flow drill-down.",
        "A kg snapshot, not a flow rate. Final grade is destoning / post-activation In Stock bags by grade, then stocked lots, then product FG kg.",
    ],
    [
        "Exklin with stone",
        "Material on the kiln / shop floor — still in process.",
        "Sum of lot_quantity where status is IN_PROGRESS, or pipeline stage is kiln feed, routing / execution, or execution (n/m) not complete",
        "Lot status and pipeline_stage from the dashboard lot lines.",
        "Name is a stage label. It is not destoning bag kg and does not add stones from crusher / destoning.",
    ],
    [
        "Exklin without stone",
        "Shop-floor complete, not yet in finished-goods stock.",
        "Sum of lot_quantity where status is COMPLETED or QC_PENDING, or stage is execution complete / shop-floor complete",
        "Lot status and pipeline_stage from the dashboard lot lines.",
        "Name is a stage label. It is not destoned (stone-removed) bag kg.",
    ],
    [
        "Kiln yield",
        "Yield chart titled Kiln Yield (All Kilns).",
        "Reuses the same plant yield %. Does not compute kiln A vs kiln B from feed vs output.",
        "If two or more lots are STOCKED / DISPATCHED / QC_PENDING / COMPLETED, that one plant % is drawn on each of the last eight completed lots. Otherwise the same % is shown as a bar on every kiln.",
        "Not a true per-kiln yield. Completing kiln output bags alone does not change this number until stock / dispatch exists.",
    ],
]


STAGE_ROWS = [
    ["CREATED", "Awaiting kiln feed", "GC (GCharcoal)"],
    ["IN_PROGRESS", "Kiln feed / Routing / Execution (n/m)", "Exklin with stone"],
    ["COMPLETED", "Shop-floor complete", "Exklin without stone"],
    ["QC_PENDING", "Quality testing", "Exklin without stone"],
    ["STOCKED", "Finished goods stock", "Final grade (if API grade stock is empty)"],
    ["DISPATCHED", "Dispatched", "Not in Material Flow; used in plant yield numerator"],
    ["CLOSED / CANCELLED", "Closed", "Ignored for active lots and Material Flow"],
]


def main() -> int:
    styles = _styles()
    page = landscape(A4)
    usable = page[0] - 24 * mm
    now = datetime.now().strftime("%Y-%m-%d")

    story = [
        Paragraph("GR Carbons — Dashboard KPI calculations", styles["title"]),
        Paragraph(
            f"{now} · current live logic on the Activated Carbon dashboard. "
            "Formulas below are what the API and UI compute today, before any next-step change.",
            styles["body"],
        ),
        Paragraph("1. KPI table", styles["h1"]),
        _table(
            ["KPI on screen", "Meaning", "Formula", "Data used", "Notes"],
            KPI_ROWS,
            styles,
            [32 * mm, 42 * mm, 52 * mm, 70 * mm, usable - 196 * mm],
        ),
        Spacer(1, 8),
        Paragraph("2. How a lot moves across the stock stages", styles["h1"]),
        Paragraph(
            "Exklin with / without stone follow lot status, not destoning capture. "
            "Pipeline stage is derived from lot status plus completed shop-floor operations.",
            styles["body"],
        ),
        _table(
            ["Lot status", "Pipeline stage shown", "Dashboard bucket"],
            STAGE_ROWS,
            styles,
            [40 * mm, 70 * mm, usable - 110 * mm],
        ),
        Spacer(1, 8),
        Paragraph("3. Related numbers on the same dashboard", styles["h1"]),
        _table(
            ["Related number", "How it is calculated"],
            [
                [
                    "Final grade stock",
                    "In Stock bag remaining kg by grade (destoning / post-activation destination In Stock). If none, stocked lot kg. If none, product finished-goods kg.",
                ],
                [
                    "Kiln feed mass (drill-down)",
                    "GC kg + Exklin with stone kg.",
                ],
                [
                    "Process loss",
                    "100 − plant yield %. Same plant yield figure, inverted.",
                ],
                [
                    "Material balance",
                    "(charged_kg + pending_kg) ÷ ordered_kg × 100.",
                ],
                [
                    "Kiln utilization",
                    "Kilns marked RUNNING ÷ kiln count × 100.",
                ],
            ],
            styles,
            [50 * mm, usable - 50 * mm],
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
        title="GR Carbons Dashboard KPI calculations",
        author="Nyra MES",
    )
    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
