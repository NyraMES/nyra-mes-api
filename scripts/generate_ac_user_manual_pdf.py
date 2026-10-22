"""GR Carbons shop-floor user manual (PDF).

Usage (repo root, venv with reportlab):
    python scripts/generate_ac_user_manual_pdf.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "GR_Carbons_User_Manual.pdf"
LOGINS_OUT = ROOT / "docs" / "GR_Carbons_Plant_Logins.pdf"
FORMULAS_OUT = ROOT / "docs" / "GR_Carbons_Calculation_Formulas.pdf"
LOGO = ROOT.parent / "nyra-mes-ui" / "src" / "assets" / "nyra-logo.png"
_PDF_OWNER_PASSWORD = "NyraServices-GRC-manual"

NAVY = colors.HexColor("#0D3A6E")
INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#475569")
RULE = colors.HexColor("#cbd5e1")
BAND = colors.HexColor("#e8eef6")
WHITE = colors.white


def _esc(value: object) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles():
    base = getSampleStyleSheet()
    return {
        "cover_kicker": ParagraphStyle(
            "CoverKicker", parent=base["Normal"], fontName="Times-Bold",
            fontSize=11, leading=14, textColor=NAVY, spaceAfter=6,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle", parent=base["Title"], fontName="Times-Bold",
            fontSize=26, leading=30, textColor=NAVY, alignment=TA_LEFT, spaceAfter=8,
        ),
        "cover_sub": ParagraphStyle(
            "CoverSub", parent=base["Normal"], fontName="Times-Italic",
            fontSize=12, leading=16, textColor=INK, spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "H1", parent=base["Heading1"], fontName="Times-Bold",
            fontSize=14, leading=18, textColor=NAVY, spaceBefore=12, spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontName="Times-Bold",
            fontSize=12, leading=15, textColor=NAVY, spaceBefore=8, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontName="Times-Roman",
            fontSize=10.5, leading=14, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "BulletBody", parent=base["Normal"], fontName="Times-Roman",
            fontSize=10.5, leading=14, textColor=INK,
        ),
        "small": ParagraphStyle(
            "Small", parent=base["Normal"], fontName="Times-Italic",
            fontSize=9, leading=12, textColor=MUTED, spaceAfter=8,
        ),
        "th": ParagraphStyle(
            "Th", parent=base["Normal"], fontName="Times-Bold",
            fontSize=9, leading=12, textColor=WHITE,
        ),
        "td": ParagraphStyle(
            "Td", parent=base["Normal"], fontName="Times-Roman",
            fontSize=9, leading=12, textColor=INK,
        ),
    }


def _p(text: str, style) -> Paragraph:
    return Paragraph(_esc(text), style)


def _rich(text: str, style) -> Paragraph:
    return Paragraph(text, style)


def _bullets(items: list[str], style) -> ListFlowable:
    return ListFlowable(
        [ListItem(_p(item, style), leftIndent=12, value="•") for item in items],
        bulletType="bullet",
        start="•",
        leftIndent=14,
        bulletFontName="Times-Roman",
        bulletFontSize=10,
        spaceBefore=2,
        spaceAfter=6,
    )


def _steps(items: list[str], style) -> ListFlowable:
    return ListFlowable(
        [ListItem(_p(item, style), leftIndent=16) for item in items],
        bulletType="1",
        start="1",
        leftIndent=18,
        bulletFontName="Times-Roman",
        bulletFontSize=10,
        spaceBefore=2,
        spaceAfter=6,
    )


def _table(headers: list[str], rows: list[list[str]], styles, col_widths) -> Table:
    head = [_rich(h, styles["th"]) for h in headers]
    body = [[_rich(cell, styles["td"]) for cell in row] for row in rows]
    table = Table([head, *body], colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
                ("GRID", (0, 0), (-1, -1), 0.3, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _draw_chrome(canvas, doc, title: str, note: str):
    canvas.saveState()
    bar_h = 16 * mm
    canvas.setFillColor(NAVY)
    canvas.rect(0, A4[1] - bar_h, A4[0], bar_h, fill=1, stroke=0)
    logo_size = 12 * mm
    if LOGO.is_file():
        canvas.drawImage(
            str(LOGO),
            A4[0] - 16 * mm - logo_size,
            A4[1] - bar_h + 2 * mm,
            width=logo_size,
            height=logo_size,
            preserveAspectRatio=True,
            anchor="c",
        )
    canvas.setFillColor(WHITE)
    canvas.setFont("Times-Bold", 9)
    canvas.drawString(16 * mm, A4[1] - 10 * mm, title)
    canvas.setFillColor(MUTED)
    canvas.setFont("Times-Roman", 8)
    year = datetime.now().year
    canvas.drawString(16 * mm, 8 * mm, f"© {year} Nyra Services. All rights reserved.")
    canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Page {doc.page}")
    canvas.setFont("Times-Italic", 7.5)
    canvas.drawString(16 * mm, 4 * mm, note)
    canvas.restoreState()


def _header_footer(canvas, doc):
    _draw_chrome(
        canvas,
        doc,
        "GR Carbons  ·  Nyra MES user manual",
        "For plant use. The corner shows your role. The sign-in name stays the user id.",
    )


def _logins_header_footer(canvas, doc):
    _draw_chrome(
        canvas,
        doc,
        "GR Carbons  ·  Plant logins",
        "Keep this sheet with the supervisor. Sign in with the user id.",
    )


def _locked_doc(path: Path, title: str) -> SimpleDocTemplate:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=22 * mm,
        bottomMargin=16 * mm,
        title=title,
        author="Nyra Services",
    )
    doc.encrypt = StandardEncryption(
        "",
        _PDF_OWNER_PASSWORD,
        canPrint=1,
        canModify=0,
        canCopy=1,
        canAnnotate=0,
        strength=128,
    )
    return doc


def build() -> Path:
    styles = _styles()
    story: list = []
    usable = A4[0] - 32 * mm

    story.append(Spacer(1, 8 * mm))
    story.append(_p("GR CARBONS", styles["cover_kicker"]))
    story.append(_p("Activated carbon plant", styles["cover_title"]))
    story.append(_p("User manual", styles["cover_sub"]))
    story.append(
        HRFlowable(width="100%", thickness=1, color=NAVY, spaceBefore=2, spaceAfter=10)
    )
    story.append(
        _p(
            "This manual is for people who receive raw material, run the kilns and destoners, "
            "screen and finish the carbon, and dispatch bags. It follows the screens in Nyra MES.",
            styles["body"],
        )
    )
    story.append(
        _p(
            f"Issued {datetime.now().strftime('%d %B %Y')}. Your menu shows only the areas your role can open.",
            styles["small"],
        )
    )

    story.append(_p("1. How a bag moves through the plant", styles["h1"]))
    story.append(
        _p(
            "Material is received at the gate, prepared, and released. A work order then says "
            "what grade, CTC, and kilograms the kiln should make. After the kiln, destoning "
            "checks for stones. Clean bags go to screening and the later steps. A bag stops "
            "when Quality sets the next destination to In Stock. Dispatch ships from In Stock.",
            styles["body"],
        )
    )
    story.append(
        _table(
            ["Stage", "Where you work", "What you leave behind"],
            [
                ["Receive", "Raw Material", "An inward number, ORD-…"],
                ["Prepare", "Raw Material → Inbound prep", "RMS bags, then outward bags"],
                ["Release", "Raw Material → Release to production", "Bags ready for the kiln"],
                ["Activate", "Execution → Activation", "Kiln bags and destoner bags"],
                ["Finish", "Execution → Post activation", "Screening and later bags"],
                ["Hold", "In Stock", "Bags waiting to be shipped"],
                ["Ship", "Dispatch", "A dispatch against a work order"],
            ],
            styles,
            [28 * mm, 72 * mm, usable - 100 * mm],
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(
        _p(
            "There is no Finished Goods step. When a bag is finished, Quality sends it to In Stock.",
            styles["body"],
        )
    )

    story.append(_p("2. Sign in and the names you see", styles["h1"]))
    story.append(
        _p(
            "Sign in with the user id you were given, for example rms@grcarbons. "
            "The Dashboard opens first. "
            "Use Show if you need to check the password as you type. "
            "Reset password emails a code to the address on the user, then you set a new password.",
            styles["body"],
        )
    )
    story.append(
        _p(
            "The top right of the screen shows your role: Administrator, Plant Manager, "
            "Raw-material section, Plant Entry, Activation, Post Activation, or Quality Control. "
            "If a nickname has been set, the nickname is shown and the role sits under it. "
            "Lists that say who saved a reading use the nickname. The record still stores the user id.",
            styles["body"],
        )
    )
    story.append(
        _bullets(
            [
                "A nickname is unique in the plant. Two people cannot use the same nickname, even if the capitals differ.",
                "An administrator creates a user under Admin → Users, enters a temporary password, and that password is emailed. The person signs in once with it and then chooses their own password.",
                "Your menu shows only the areas your role can open.",
            ],
            styles["bullet"],
        )
    )
    story.append(_p("Who does the work", styles["h2"]))
    story.append(
        _table(
            ["Work", "Who saves it"],
            [
                ["Gate receipt", "Plant Manager, Production Planner, Administrator, or Plant Entry"],
                ["Bag generation", "Raw-material section"],
                ["Lab", "Quality Control"],
                ["Debit note", "Plant Manager, Production Planner, or Administrator"],
                ["RMS outward", "Raw-material section"],
                ["Release to production", "Raw-material section, Plant Manager, or Production Planner"],
                ["Kiln feed, kiln output, destoning", "Activation. A shop-floor operator can run the machines."],
                ["Kiln output quality, destoning quality, post-activation quality", "Quality Control. A Plant Manager or Production Planner can also open these."],
                ["Screening through blending", "Post Activation. A shop-floor operator can run the machines."],
                ["Destoner CTC allocation and Stock Reallocation", "Plant Manager, Production Planner, or Administrator"],
                ["Dispatch", "Plant Manager or Production Planner"],
            ],
            styles,
            [62 * mm, usable - 62 * mm],
        )
    )
    story.append(_p("The left menu", styles["h2"]))
    story.append(
        _table(
            ["Menu", "Use it to"],
            [
                ["Dashboard", "See the plant, machine use, and trace a bag or work order"],
                ["Raw Material", "Gate receipt, inbound prep, release, and raw-material reports"],
                ["Execution → Activation", "Kiln feed, kiln output, destoning, and kiln readings"],
                ["Execution → Post activation", "Screening through blending, then quality"],
                ["Dispatch", "Ship In Stock bags for a work order"],
                ["Reports", "Read what was done. Reports do not change the bags"],
                ["Admin", "Users, suppliers, Destoner CTC allocation, kiln settings, work orders, Stock Reallocation"],
                ["Masters", "Plant rules, mesh, machines, and inbound settings. Nyra only."],
            ],
            styles,
            [55 * mm, usable - 55 * mm],
        )
    )
    story.append(
        _p(
            "User ids, passwords, and the screens each login can open are on the separate plant logins sheet.",
            styles["body"],
        )
    )

    story.append(_p("3. Numbers on bags and orders", styles["h1"]))
    story.append(
        _p(
            "Each number has one job. Use the number printed on the bag or shown on the screen. "
            "Do not invent a second number for the same bag.",
            styles["body"],
        )
    )
    story.append(
        _table(
            ["Number", "Meaning"],
            [
                ["ORD-…", "One gate receipt. This is the inward until it is released."],
                ["WO-…", "A work order: grade, CTC, and kilograms to make."],
                ["RI_BAG_…", "A raw-material bag made after the gate weight is saved."],
                ["RO_BAG_…", "An outward bag after rotary preparation. This is what the kiln can load."],
                ["KA_… or KB_…", "A kiln output bag. KA is Kiln A. KB is Kiln B. The middle is the date."],
                ["DS_…", "A destoner bag."],
                ["SC_, DD_, CR_, DM_, BL_", "Screening, de-dusting, crushing, de-magnetisation, blending."],
                ["DN-…", "A debit note raised after lab, when one is needed."],
            ],
            styles,
            [42 * mm, usable - 42 * mm],
        )
    )
    story.append(Spacer(1, 2 * mm))
    story.append(
        _p(
            "The date in a bag number is the India date, written day-month-year. "
            "Example: 121026 is 12 October 2026. A bag keeps the date it was created. "
            "It does not change later in the day.",
            styles["body"],
        )
    )

    story.append(_p("4. Raw material", styles["h1"]))
    story.append(_p("Gate receipt", styles["h2"]))
    story.append(
        _p(
            "Plant Entry and the supervisor open Raw Material → Gate receipt. "
            "The Raw-material section login does not see this tab. "
            "Record one inward for the truck or delivery you are receiving. Saving does not create bags.",
            styles["body"],
        )
    )
    story.append(
        _steps(
            [
                "Choose the supplier.",
                "Enter the DC number, the supplier weight in kilograms, and our weight in kilograms.",
                "Our weight is the quantity the plant received. It must be greater than zero and not more than the supplier weight.",
                "Save the inward. The screen gives it an ORD number.",
            ],
            styles["bullet"],
        )
    )
    story.append(_p("Inbound prep", styles["h2"]))
    story.append(_p("RMS inward bags", styles["h2"]))
    story.append(
        _p(
            "The Raw-material section login opens Inbound prep → Bag generation. "
            "Type each bag weight and click Generate bag. "
            "Keep adding bags until the bag total matches our weight. Bags are numbered RI_BAG_…. "
            "The system does not split the weight for you.",
            styles["body"],
        )
    )
    story.append(
        _p(
            "If the bags are still short of our weight, the screen asks you to confirm before you go on to Lab.",
            styles["body"],
        )
    )
    story.append(_p("Lab", styles["h2"]))
    story.append(
        _p(
            "Quality Control opens Lab and enters moisture, dust, and volatility, each as a percent from 0 to 100, then approves or denies. "
            "The values stay on the screen after save. The Raw-material section and the supervisor do not save Lab. "
            "Weights stay in kilograms. Deny stops this inward.",
            styles["body"],
        )
    )
    story.append(
        _p(
            "A debit note is optional and is raised by the supervisor after lab, when our weight is less than the supplier weight "
            "or when moisture is above the plant limit (20 percent unless Masters has changed it). "
            "Enter the debit value. The note is numbered DN-…. It does not stop RMS outward. "
            "Quality Control and the Raw-material section do not raise it.",
            styles["body"],
        )
    )
    story.append(_p("RMS outward", styles["h2"]))
    story.append(
        _p(
            "The Raw-material section login creates the rotary output bags after Lab. "
            "Choose Rotary A or Rotary B and add at least one line. A grade, Unburnt, or Stones each counts. "
            "The total cannot be more than the inward weight. When the outward is finished, click "
            "RMS outward complete. The inward is then ready for release. You do not need a separate raw-material quality step.",
            styles["body"],
        )
    )
    story.append(_p("Release to production", styles["h2"]))
    story.append(
        _p(
            "The Raw-material section, the Plant Manager, or the Production Planner opens Release to production and releases the inward. "
            "Release waits until RMS outward is complete. Released outward bags can be loaded on the kiln. "
            "If the inward is already released, the release button stays off. After release, go to Execution.",
            styles["body"],
        )
    )

    story.append(_p("5. Work orders", styles["h1"]))
    story.append(
        _p(
            "A work order is the production demand. Open Admin → Work orders. Enter the grade, the CTC, and the kilograms. "
            "The screen numbers it WO-…. CTC is entered once here. Later screens show that CTC. They do not ask you to type it again, "
            "except kiln output quality, which measures the actual CTC of the bag that came out of the kiln.",
            styles["body"],
        )
    )
    story.append(
        _p(
            "Create the work order before kiln feed. The kiln operator picks this number. "
            "It is not a customer order. Customer orders are not recorded in this plant.",
            styles["body"],
        )
    )
    story.append(
        _p(
            "Stock Reallocation, under Admin, moves an In Stock bag onto another work order of the same grade. "
            "The bag keeps its number and its earlier work order in the history. A different grade, the same work order, "
            "or a bag that is not In Stock is refused.",
            styles["body"],
        )
    )

    story.append(_p("6. Activation", styles["h1"]))
    story.append(
        _p(
            "Open Execution. The header shows the flow Kiln Feed → Kiln Output → Destoning, "
            "and a line for kiln parameters. Choose the step from that flow.",
            styles["body"],
        )
    )
    story.append(_p("Kiln feed", styles["h2"]))
    story.append(
        _steps(
            [
                "Pick the work order number, then the kiln.",
                "A kiln may hold more than one open work order when the grade and CTC are the same. A different grade or CTC waits until the feed already on that kiln has been covered by output.",
                "Load released outward bags. A bag already loaded is not offered again. Unburnt and Stones stay off the kiln. The outward bag does not have to match the work-order grade.",
                "A work order leaves the open list once kiln output covers its quantity.",
                "Feed can continue while output is taken. You do not wait for the kiln to empty before the next load.",
            ],
            styles["bullet"],
        )
    )
    story.append(_p("Kiln output", styles["h2"]))
    story.append(
        _p(
            "Enter the weight only. You do not pick the work order on this screen. "
            "The bag is tagged to an open work order on that kiln that still has feed left, using the earliest feed first. "
            "Output cannot be more than what is still in the kiln (everything loaded so far, minus everything already taken out). "
            "If nothing is loaded, output is blocked. Kiln A bags start with KA_. Kiln B bags start with KB_. "
            "The current kiln settings are shown on this screen and are stored on the new bag.",
            styles["body"],
        )
    )
    story.append(
        _p(
            "Quality Control records kiln output quality, including the actual CTC. Activation does not open that form. "
            "If the measured CTC matches the work order, that weight counts toward the work order. "
            "If it does not match, the bag stays for destoning by the measured CTC and does not fulfill the work order.",
            styles["body"],
        )
    )
    story.append(_p("Kiln parameters", styles["h2"]))
    story.append(
        _p(
            "On Activation, Kiln Parameters is where the engineer records T1, T2, T3, Main Damper (MD %), Boiler Damper (BD %), Induced Draft (ID %), and Boiler Pressure every 30 minutes. A missed interval stays locked until a plant manager approves it. "
            "A missed interval is locked until a plant manager approves it, and then the values can be entered. "
            "The standing settings (residence time, temperatures, steam, oxygen, pressure) are kept under Admin → Kiln parameters. "
            "Those settings stay until someone changes them. They are not entered again every day. "
            "Each save is kept in the change log, with who saved it and when. "
            "A new kiln output bag keeps the settings that were current when it was created. Traceability shows those settings on that bag. "
            "Scrap is not a kiln parameter. "
            "Residence time also sets the designed monthly kilograms on the dashboard: a shorter residence raises the designed output, a longer residence lowers it. Other machines keep the capacity entered in Masters.",
            styles["body"],
        )
    )
    story.append(_p("Destoning", styles["h2"]))
    story.append(
        _p(
            "Before the shift loads a destoner, a supervisor or administrator sets today’s CTC under Admin → Destoner CTC allocation. "
            "There are four destoners: Destoner 1, Destoner 2, Destoner 3, and Destoner 4. "
            "Load bag accepts a kiln bag whose CTC matches that destoner’s CTC for today.",
            styles["body"],
        )
    )
    story.append(
        _p(
            "Quality Control records destoning quality. It is a stones check. Stones Yes sends the bag back to destoning. "
            "Stones No sends it to Screening. Destoning does not send a bag to In Stock.",
            styles["body"],
        )
    )

    story.append(_p("7. Post activation", styles["h1"]))
    story.append(
        _p(
            "Open Execution. The header says Screening through blending, then In Stock. "
            "Each process has a loader. Load a bag, then tag the output weight. "
            "Output weight cannot be more than the kilograms still on the loader (in, minus out). "
            "The output list on the shop floor shows bags from the current plant day. Earlier days stay on the dashboard and in reports. "
            "The loader still shows the bags that are on the machine.",
            styles["body"],
        )
    )
    story.append(_p("Screening", styles["h2"]))
    story.append(
        _steps(
            [
                "Choose the mesh first. Meshes are A to E, as set in Masters.",
                "Load bag stays off until a mesh is chosen.",
                "That mesh stays while bags are on the loader. Unload every bag before you choose a different mesh.",
                "Tag only a grade that belongs to that mesh. Enter the weight and click Tag.",
            ],
            styles["bullet"],
        )
    )
    story.append(_p("Later processes", styles["h2"]))
    story.append(
        _bullets(
            [
                "De-dusting and de-magnetisation use the grade Exklin.",
                "Crushing uses the crushing grades shown on the screen.",
                "Blending follows the same load, then tag, pattern.",
                "The work order number and its CTC are shown. Do not type the CTC again.",
            ],
            styles["bullet"],
        )
    )
    story.append(_p("Quality and the next destination", styles["h2"]))
    story.append(
        _p(
            "Quality Control opens Quality. Activation and Post Activation do not save it. "
            "The list shows output bags from the current plant day. Set Next Destination and save. "
            "The bag then waits on that process’s Load bag list.",
            styles["body"],
        )
    )
    story.append(
        _bullets(
            [
                "In Stock — the bag is finished. It leaves the process line and can be dispatched.",
                "Screening, De-dusting, Crushing, De-magnetize, or Blending — load the bag on that process next.",
            ],
            styles["bullet"],
        )
    )
    story.append(
        _p(
            "A saved quality result cannot be edited. If the destination is wrong, do not try to overwrite it. "
            "Ask a supervisor before any correction outside this screen.",
            styles["body"],
        )
    )

    story.append(_p("8. In Stock and dispatch", styles["h1"]))
    story.append(
        _p(
            "In Stock is not a machine. It is the list of bags whose quality destination is In Stock and that still have kilograms left. "
            "Dispatch draws from this list.",
            styles["body"],
        )
    )
    story.append(
        _steps(
            [
                "Open Dispatch.",
                "Pick the work order number.",
                "The list shows In Stock bags on that work order.",
                "Tick the In Stock bags to ship, or use Select all. The screen shows dispatched kg, pending kg, and the kg you have selected.",
                "Dispatch uses the selected bags. It does not take kilograms from a bag you left unticked, and it cannot be more than the pending work-order quantity.",
                "Shipped kilograms come off the bag. A bag that is fully shipped leaves the available list.",
            ],
            styles["bullet"],
        )
    )

    story.append(_p("9. Looking back", styles["h1"]))
    story.append(_p("Dashboard", styles["h2"]))
    story.append(
        _p(
            "The plant dashboard opens with three dials: plant yield, overall process efficiency, and supplier efficiency. "
            "The figures use all records to date. Machine output is the current month. The view refreshes every 10 minutes. "
            "Plant yield is finished kilograms divided by raw material charged. "
            "Overall process efficiency subtracts finished loss from 100. A stream still in process stays off that number. "
            "Supplier efficiency is 0.5 × recovery + 0.3 × lab pass + 0.2 × weigh score. "
            "Choosing a dial or a bar opens that area. Material in plant is charcoal, awaiting kiln, in process, and in stock. "
            "Process Tracking holds mesh compliance, destoner CTC, deviation, and the efficiency detail. "
            "Kiln designed output follows the residence time. The other machines use the monthly capacity from Masters. "
            "The arithmetic for each dial is on the separate calculation formulas sheet. "
            "These charts do not change a bag.",
            styles["body"],
        )
    )
    story.append(_p("Traceability", styles["h2"]))
    story.append(
        _p(
            "On the Dashboard, open Traceability. Look up a work order, a bag, an inward, or a dispatch from this month’s list. "
            "The screen walks back to the gate receipt and the supplier. If more than one supplier fed the work order, "
            "the screen says so and shows each supplier’s feed kilograms. A kiln output bag also shows the kiln settings stored on it. "
            "The customer is not shown.",
            styles["body"],
        )
    )
    story.append(_p("Reports", styles["h2"]))
    story.append(
        _p(
            "Open Reports on Raw Material, on Activation, or on Post Activation. "
            "Pick From and To. The calendar closes when the date is chosen. "
            "The table lists the bags and readings in that range. Type in Search to narrow the rows, for example a bag number or a work order. "
            "You can export to Excel. Reports are read-only.",
            styles["body"],
        )
    )
    story.append(
        _bullets(
            [
                "Supplier name and debit-note rows are shown to the Plant Manager, the Production Planner, the Administrator, and the super administrator. Other logins see the weights and bag numbers without the supplier.",
                "User performance lists who saved the readings. It is shown to the Plant Manager, the Production Planner, the Administrator, and a read-only viewer.",
                "Plant Production reports, for the Plant Manager and a viewer, are the summary charts: work in process, raw-material loss, kiln yield, and grade stock.",
                "Plant Entry does not have a Reports tab. The Raw-material section uses Raw Material → Reports.",
            ],
            styles["bullet"],
        )
    )

    story.append(_p("10. Setup that the shop floor depends on", styles["h1"]))
    story.append(
        _table(
            ["Who", "Where", "When"],
            [
                ["Supervisor", "Admin → Destoner CTC allocation", "Each day, before destoner load. One CTC per destoner."],
                ["Supervisor", "Admin → Kiln parameters", "When the standing kiln settings change. The change log keeps who saved each setting. Scrap is not a kiln parameter."],
                ["Supervisor", "Admin → Stock Reallocation", "When an In Stock bag must move to another work order of the same grade."],
                ["Planner", "Admin → Work orders", "Before the kiln is fed for that demand."],
                ["Admin", "Admin → Users", "When a person joins, or when a nickname must change."],
                ["Admin", "Admin → Suppliers", "When a new supplier delivers to the gate."],
                ["Admin", "Masters → Mesh", "When the grades on mesh A–E change."],
                ["Nyra", "Masters → Process rules", "Moisture, CTC decimals, bag rules, and minutes from load to output for a 500 kg bag."],
                ["Admin", "Masters → Inbound settings", "Rotary names and the outward grades, including Unburnt and Stones."],
            ],
            styles,
            [28 * mm, 58 * mm, usable - 86 * mm],
        )
    )

    story.append(_p("11. When a button stays off", styles["h1"]))
    story.append(
        _bullets(
            [
                "Release stays off until RMS outward is complete, and again after the inward is already released. An administrator login does not save release.",
                "Kiln output stays off when the kiln has no feed left, or when the weight is larger than what is still in the kiln.",
                "Destoner Load bag stays off when today’s CTC is not set, or when the bag CTC does not match that destoner.",
                "Screening Load bag stays off until you choose a mesh.",
                "A quality row stays locked after it is saved.",
                "If your menu is missing a screen, your role does not include it. Ask an admin. Do not share another person’s sign-in.",
            ],
            styles["bullet"],
        )
    )

    story.append(CondPageBreak(40 * mm))
    story.append(_p("12. A short day on the floor", styles["h1"]))
    story.append(
        _steps(
            [
                "Gate: Plant Entry or a supervisor saves the inward with DC number, supplier weight, and our weight. Saving does not create bags.",
                "Raw-material section: generate each bag by kilograms. Quality Control: lab. Raw-material section: at least one outward line, then RMS outward complete.",
                "Raw-material section, Plant Manager, or Production Planner: release to production.",
                "Confirm today’s Destoner CTC allocation, and that the work order exists.",
                "Activation: follow Kiln Feed → Kiln Output → Destoning. Load outward bags, take kiln output by weight (the current kiln settings are stored on that bag), then destone.",
                "Quality Control: kiln output quality and destoning quality. Stones No goes to screening.",
                "Post Activation: screening, mesh first, then load, then tag the grades on that mesh.",
                "Quality Control: send the bag to the next process, or to In Stock.",
                "Plant Manager or Production Planner: dispatch the selected In Stock bags for that work order.",
            ],
            styles["bullet"],
        )
    )
    story.append(
        _p(
            "If a screen and this manual disagree, follow the screen and tell the supervisor. "
            "The screen is the live rule for that bag.",
            styles["body"],
        )
    )

    doc = _locked_doc(OUT, "GR Carbons user manual")
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return OUT


def build_logins() -> Path:
    styles = _styles()
    story: list = []
    usable = A4[0] - 32 * mm

    story.append(Spacer(1, 6 * mm))
    story.append(_p("GR CARBONS", styles["cover_kicker"]))
    story.append(_p("Plant logins", styles["cover_title"]))
    story.append(
        _p(
            f"Sign-in sheet  ·  {datetime.now().strftime('%d %b %Y')}",
            styles["cover_sub"],
        )
    )
    story.append(
        _p(
            "Sign in with the user id, not the email. "
            "The six plant logins use Welcome!123 unless that person has already chosen a new password. "
            "Plant Entry is created on Admin → Users. Its password is the temporary password entered on that screen, and it is emailed. "
            "The nyraservices login keeps the password issued to Nyra.",
            styles["body"],
        )
    )
    story.append(
        _table(
            ["User id", "Password", "Screens"],
            [
                [
                    "admin@grcarbons",
                    "Welcome!123",
                    "Plant dashboard. Raw Material, including gate receipt. Execution, including quality. Admin: users, suppliers, Destoner CTC allocation, kiln parameters, work orders, Stock Reallocation. Does not dispatch, does not open Masters, and does not save release.",
                ],
                [
                    "manager@grcarbons",
                    "Welcome!123",
                    "Plant dashboard. Raw Material, including gate receipt, debit note, and release. Execution, including quality. Dispatch. Reports. Admin, same as the administrator. Does not open Masters.",
                ],
                [
                    "rms@grcarbons",
                    "Welcome!123",
                    "Week dashboard of our-weight kilograms. Raw Material → Inbound prep (bag generation and RMS outward), release, and raw-material reports. No gate receipt and no supplier name. No execution, dispatch, admin, or masters.",
                ],
                [
                    "activation@grcarbons",
                    "Welcome!123",
                    "Week dashboard of the bags this person saved. Execution → Activation: kiln feed, kiln output, and destoning. Quality tabs stay closed.",
                ],
                [
                    "postactivation@grcarbons",
                    "Welcome!123",
                    "Week dashboard of the bags this person saved. Execution → Post activation: screening through blending. The quality tab stays closed.",
                ],
                [
                    "quality@grcarbons",
                    "Welcome!123",
                    "Week dashboard of quality checks. Lab on Inbound prep. Kiln output quality, destoning quality, and post-activation quality.",
                ],
                [
                    "Plant Entry",
                    "Emailed at creation",
                    "Create this login on Admin → Users and choose Plant Entry. Gate receipt only. The supplier is shown. No inbound prep, release, execution, dispatch, reports, admin, or masters.",
                ],
            ],
            styles,
            [38 * mm, 32 * mm, usable - 70 * mm],
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(
        _p(
            "A Production Planner sees the same screens as the Plant Manager. "
            "A shop-floor operator can run Activation and Post activation machines, and does not open quality.",
            styles["body"],
        )
    )

    doc = _locked_doc(LOGINS_OUT, "GR Carbons plant logins")
    doc.build(story, onFirstPage=_logins_header_footer, onLaterPages=_logins_header_footer)
    return LOGINS_OUT


def _formulas_header_footer(canvas, doc):
    _draw_chrome(
        canvas,
        doc,
        "GR Carbons  ·  Calculation formulas",
        "Read-only scores. They do not change a bag.",
    )


def build_formulas() -> Path:
    styles = _styles()
    story: list = []
    usable = A4[0] - 32 * mm

    story.append(Spacer(1, 6 * mm))
    story.append(_p("GR CARBONS", styles["cover_kicker"]))
    story.append(_p("Calculation formulas", styles["cover_title"]))
    story.append(
        _p(
            f"Scores on the plant dashboard  ·  {datetime.now().strftime('%d %b %Y')}",
            styles["cover_sub"],
        )
    )
    story.append(
        _p(
            "These are the formulas the screens use. A percent is shown to one decimal place. "
            "When the denominator is zero, or a measurement has not finished, the score stays blank and the screen says Not Evaluated. "
            "A missing measurement is never treated as zero. These scores do not create or change a bag.",
            styles["body"],
        )
    )

    story.append(_p("Plant yield", styles["h1"]))
    story.append(
        _p(
            "Plant yield % = finished kilograms ÷ raw material charged to production × 100.",
            styles["body"],
        )
    )
    story.append(
        _p(
            "Finished kilograms are the stocked lot quantity plus the last dispatched kilograms on a dispatched lot. "
            "When that total is still zero, the screen uses finished-goods stock plus every dispatched kilogram. "
            "Charged kilograms are the raw material released to production. "
            "The dial arc stops at 100. The number itself can show above 100. "
            "While material is only in process, and nothing is stocked or dispatched, yield stays blank.",
            styles["body"],
        )
    )

    story.append(_p("Material in plant", styles["h1"]))
    story.append(
        _p(
            "Material in plant = charcoal + awaiting kiln + in process + in stock. Dispatched kilograms stay outside this total.",
            styles["body"],
        )
    )
    story.append(
        _table(
            ["Part", "What is added"],
            [
                ["Charcoal", "Received kilograms that are not released yet."],
                ["Awaiting kiln", "On a released lot that has not started: lot kilograms minus dispatched kilograms minus kilograms already In Stock."],
                ["In process", "The same remainder on a lot that is on the kiln or the shop floor."],
                ["In stock", "Grade stock. When that is empty, stocked lots, then finished-goods stock."],
            ],
            styles,
            [32 * mm, usable - 32 * mm],
        )
    )

    story.append(_p("Supplier efficiency", styles["h1"]))
    story.append(
        _p(
            "The overview dial is the plant total. The Raw Material tab ranks each supplier a login can see. "
            "A missing part is left out and the remaining weights are scaled to 1. The figures use all receipts to date.",
            styles["body"],
        )
    )
    story.append(
        _table(
            ["Part", "Formula"],
            [
                ["Usable recovery", "100 × kilograms released to production ÷ plant weighbridge kilograms."],
                ["Weigh match", "100 × plant kilograms ÷ supplier DC kilograms."],
                ["Weigh score", "100 minus the gap between weigh match and 100. The score cannot go below 0."],
                ["Lab pass", "100 × lab approvals ÷ lab decisions."],
                ["Efficiency", "0.5 × recovery + 0.3 × lab pass + 0.2 × weigh score. A missing part is left out and the remaining weights are scaled to 1."],
            ],
            styles,
            [36 * mm, usable - 36 * mm],
        )
    )

    story.append(_p("Overall process efficiency", styles["h1"]))
    story.append(
        _p(
            "Process input = our weight, else the inward quantity, added up for inward orders that already have a graded outward bag. "
            "Each loss % = 100 × loss kilograms ÷ process input. "
            "Actual efficiency % = 100 minus the sum of those loss percentages. "
            "The dial uses the streams that have finished. A stream still in process stays off the number. "
            "There is no approved loss standard, so the reference stays Not Evaluated. This score is not plant yield.",
            styles["body"],
        )
    )
    story.append(
        _table(
            ["Stream", "Loss kilograms"],
            [
                ["Stones", "Outward bag weight graded Stones. The rotary name is ignored. No Stones bag means Not Evaluated."],
                ["Unburnt", "Outward bag weight graded Unburnt. No Unburnt bag means Not Evaluated. Both stay off the kiln."],
                ["Kiln", "For each kiln, feed is due when the minutes since load reach that kiln’s residence time. Loss = due kilograms minus that kiln’s output. Feed still inside residence stays in process. A kiln with feed and no residence makes the kiln Not Evaluated. Output is not shared across kilns."],
                ["Screening, de-dusting, crushing, de-magnetisation, blending", "Loaded kilograms minus the output bags that name those loaded bags. A group still on the loader stays in process until every bag has passed its Masters minutes. De-dusting, de-magnetisation, and blending finish when the output bag is saved. An unknown input weight makes that machine Not Evaluated."],
            ],
            styles,
            [38 * mm, usable - 38 * mm],
        )
    )
    story.append(Spacer(1, 2 * mm))
    story.append(
        _p(
            "Destoning and material handling are stored in Masters and are not loss lines. "
            "The minutes below are the top of the 500 kg estimate, so a bag still inside the estimate stays in process. "
            "Crushing and blending have no minutes until the plant sets them.",
            styles["body"],
        )
    )
    story.append(
        _table(
            ["Machine", "Minutes from load to output"],
            [
                ["Screening", "20"],
                ["De-dusting", "10"],
                ["Destoning", "15 (stored only)"],
                ["De-magnetisation", "5"],
                ["Material handling", "10 (stored only)"],
                ["Crushing", "Blank"],
                ["Blending", "Blank"],
            ],
            styles,
            [55 * mm, usable - 55 * mm],
        )
    )

    story.append(_p("Process tracking", styles["h1"]))
    story.append(
        _table(
            ["Score", "Formula"],
            [
                ["Mesh compliance", "100 × screening tags whose grade is on that mesh in Masters ÷ screening tags that have a mesh and a grade. An empty mesh list stays Not Evaluated. A refused mesh is not stored."],
                ["Destoner CTC", "100 × saved destoner loads ÷ saved destoner loads. A saved load already matched the destoner CTC. No load stays Not Evaluated. CTC is rounded to the Masters decimals, then the two values must be equal."],
                ["Deviation", "100 × runs with a deviation ÷ evaluated runs. A deviation is a screening grade off its mesh, or a kiln output whose measured CTC does not match the work order. Evaluated runs are those screening tags, destoner loads, and saved kiln-output quality rows. Stones marked Yes is not a deviation."],
            ],
            styles,
            [36 * mm, usable - 36 * mm],
        )
    )

    story.append(_p("Machines", styles["h1"]))
    story.append(
        _table(
            ["Score", "Formula"],
            [
                ["Kiln designed kg for the month", "Masters monthly capacity × (60 ÷ residence minutes), rounded, and at least 1 kg. Masters capacity is the output at 60 minutes. No residence uses the Masters capacity. Other machines use their Masters monthly capacity. The fallback is 15,000 kg."],
                ["Utilization", "100 × output saved this calendar month ÷ designed kilograms for the month. Green is 90% and above. Amber is 70% up to green. Red is below 70%. Masters can change these bands."],
                ["Kiln cycle", "Elapsed hours ÷ (residence minutes ÷ 60), capped at 100, while that kiln is loaded and a residence time is set."],
                ["Kilns running", "100 × kilns marked running ÷ the number of kilns."],
            ],
            styles,
            [42 * mm, usable - 42 * mm],
        )
    )
    story.append(
        _p(
            "Month-to-date output uses the calendar month on the screen. Shop-floor lists for today use the plant day in Asia/Kolkata. "
            "The dashboard keeps history so a past bag still counts in the month.",
            styles["body"],
        )
    )

    doc = _locked_doc(FORMULAS_OUT, "GR Carbons calculation formulas")
    doc.build(story, onFirstPage=_formulas_header_footer, onLaterPages=_formulas_header_footer)
    return FORMULAS_OUT


if __name__ == "__main__":
    print(build())
    print(build_logins())
    print(build_formulas())
