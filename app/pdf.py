"""Renders a quote as a branded one-to-two page PDF with ReportLab."""
import html
import io
from datetime import date

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .catalog import Catalog
from .quotes import Quote

GREY = HexColor("#5B6470")
LIGHT = HexColor("#EEF2F6")


def _fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"  # portable (no %-d, which fails on Windows)


def _qty(q: float) -> str:
    return f"{q:,.0f}" if q == int(q) else f"{q:,.2f}"


def render_pdf(quote: Quote, catalog: Catalog) -> bytes:
    brand = HexColor(catalog.company.get("brand_color", "#1F4E79"))
    e = html.escape
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title=f"Quote {quote.number}", author=catalog.company["name"])

    body = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11, textColor=GREY)
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=brand,
                       spaceBefore=10, spaceAfter=4)
    right = ParagraphStyle("right", parent=body, alignment=TA_RIGHT)
    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=white)
    sub = ParagraphStyle("sub", parent=body, textColor=white)
    sub_r = ParagraphStyle("subr", parent=sub, alignment=TA_RIGHT)

    c = catalog.company
    story = []

    header = Table([[
        [Paragraph(e(c["name"]), title), Paragraph(f"{e(c['phone'])} &nbsp;&bull;&nbsp; {e(c['email'])}", sub)],
        [Paragraph("<b>QUOTE</b>", ParagraphStyle("q", parent=title, alignment=TA_RIGHT)),
         Paragraph(f"{e(quote.number)}<br/>Issued {_fmt_date(quote.issued)}", sub_r)],
    ]], colWidths=[4.3 * inch, 2.8 * inch])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), brand),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story += [header, Spacer(1, 12)]

    cust = quote.customer
    who = "<br/>".join(e(x) for x in [cust.name, cust.address, cust.email] if x)
    meta = Table([[
        [Paragraph("<b>Prepared for</b>", small), Paragraph(who, body)],
        [Paragraph("<b>Valid until</b>", small), Paragraph(_fmt_date(quote.valid_until), body)],
    ]], colWidths=[4.3 * inch, 2.8 * inch])
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [meta]

    story += [Paragraph("Scope of work", h), Paragraph(e(quote.scope_summary), body)]

    p = quote.priced
    rows = [["Service", "Qty", "Unit", "Unit price", "Amount"]]
    for line in p.lines:
        label = e(line.name) + (f"<br/><font size=8 color='#5B6470'>{e(line.note)}</font>" if line.note else "")
        if line.recurring:
            label += "<br/><font size=8 color='#5B6470'>Recurring, billed annually</font>"
        rows.append([Paragraph(label, body), _qty(line.quantity), line.unit,
                     f"${line.unit_price:,.2f}", f"${line.amount:,.2f}"])

    totals = [("Subtotal", p.subtotal)]
    if p.discount:
        totals.append((p.discount_label, -p.discount))
    if p.minimum_adjustment:
        totals.append(("Minimum job adjustment", p.minimum_adjustment))
    totals.append((f"Tax ({catalog.pricing.get('tax_rate', 0) * 100:g}%)", p.tax))
    first_total_row = len(rows)
    for label, amount in totals:
        sign = "-" if amount < 0 else ""
        rows.append([Paragraph(e(label), right), "", "", "", f"{sign}${abs(amount):,.2f}"])
    rows.append([Paragraph("<b>Total</b>", right), "", "", "", f"${p.total:,.2f}"])
    spans = [("SPAN", (0, r), (3, r)) for r in range(first_total_row, len(rows))]

    table = Table(rows, colWidths=[3.25 * inch, 0.55 * inch, 0.95 * inch, 1.15 * inch, 1.2 * inch], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), brand),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (2, 0), (2, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, first_total_row - 1), [white, LIGHT]),
        ("LINEABOVE", (3, first_total_row), (-1, first_total_row), 0.6, GREY),
        ("LINEABOVE", (3, -1), (-1, -1), 1.2, brand),
        ("FONTNAME", (4, -1), (4, -1), "Helvetica-Bold"),
        ("FONTSIZE", (4, -1), (4, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        *spans,
    ]))
    story += [Paragraph("Pricing", h), table]

    if quote.assumptions:
        story += [Paragraph("Assumptions", h)]
        story += [Paragraph(f"&bull; {e(a)}", body) for a in quote.assumptions]
    if quote.terms:
        story += [Paragraph("Terms", h)]
        story += [Paragraph(f"&bull; {e(t)}", body) for t in quote.terms]

    sign = Table([["Accepted by", "", "Date", ""]], colWidths=[0.95 * inch, 3.3 * inch, 0.5 * inch, 2.3 * inch])
    sign.setStyle(TableStyle([
        ("LINEBELOW", (1, 0), (1, 0), 0.6, GREY), ("LINEBELOW", (3, 0), (3, 0), 0.6, GREY),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (-1, -1), GREY),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    story += [Spacer(1, 22), sign, Spacer(1, 10),
              Paragraph(f"{e(c['name'])} &bull; {e(c.get('address', ''))}", small)]

    doc.build(story)
    return buf.getvalue()
