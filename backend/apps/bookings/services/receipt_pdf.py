"""Server-side receipt PDF generation.

The Celery worker is the source of truth for the receipt attachment: it
regenerates the PDF from the database (booking + successful payments) and never
depends on anything the browser produced. Generation is done entirely in
memory (``BytesIO``) so there are no temporary files that could be deleted
before, or be inaccessible to, the worker.

reportlab is a pure-Python dependency (no system libraries), so it runs
identically on the web service and the worker.
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger("apps")


def render_receipt_pdf(receipt: dict) -> bytes:
    """Render a ``ReceiptSerializer`` payload into PDF bytes.

    Returns the raw PDF bytes. Raises on failure so the caller (the email task)
    can decide whether to send without the attachment or fail — it must NOT
    silently pretend a receipt was attached.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 20 * mm
    right = width - 20 * mm
    y = height - 25 * mm

    hotel = receipt.get("hotel", {}) or {}
    guest = receipt.get("guest", {}) or {}
    currency = receipt.get("currency", "NGN")

    def line(label, value, *, bold=False, size=10, gap=6 * mm):
        nonlocal y
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(left, y, str(label))
        if value is not None:
            pdf.setFont("Helvetica", size)
            pdf.drawRightString(right, y, str(value))
        y -= gap

    # Header
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(left, y, str(hotel.get("name", "J-ONE HOTEL & LODGE")))
    y -= 7 * mm
    pdf.setFont("Helvetica", 9)
    for part in (hotel.get("address"), hotel.get("phone"), hotel.get("email")):
        if part:
            pdf.drawString(left, y, str(part))
            y -= 4.5 * mm
    y -= 3 * mm
    pdf.setStrokeColor(colors.HexColor("#c9a227"))
    pdf.setLineWidth(1.2)
    pdf.line(left, y, right, y)
    y -= 9 * mm

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(left, y, "PAYMENT RECEIPT")
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(right, y, f"Ref: {receipt.get('receipt_reference', '')}")
    y -= 9 * mm

    line("Booking reference", receipt.get("booking_reference"), bold=True)
    line("Status", receipt.get("payment_status_label") or receipt.get("payment_status"))
    line("Issued", (receipt.get("issued_at") or "")[:19].replace("T", " "))
    y -= 2 * mm

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left, y, "Guest")
    y -= 6 * mm
    line("Name", guest.get("name"))
    if guest.get("email"):
        line("Email", guest.get("email"))
    if guest.get("phone"):
        line("Phone", guest.get("phone"))
    y -= 2 * mm

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left, y, "Stay")
    y -= 6 * mm
    line("Room", f"{receipt.get('rooms', 1)} × {receipt.get('room_type', '')}")
    rooms = receipt.get("room_numbers") or []
    if rooms:
        line("Room number(s)", ", ".join(str(r) for r in rooms))
    line("Check-in", receipt.get("check_in"))
    line("Check-out", receipt.get("check_out"))
    line("Nights", receipt.get("nights"))
    y -= 2 * mm

    pdf.setStrokeColor(colors.HexColor("#dddddd"))
    pdf.line(left, y, right, y)
    y -= 8 * mm

    def money_line(label, value, *, bold=False):
        line(label, f"{currency} {value}", bold=bold)

    money_line("Subtotal", receipt.get("subtotal"))
    if str(receipt.get("discount", "0")) not in ("0", "0.00", "0.0"):
        money_line("Discount", receipt.get("discount"))
    if str(receipt.get("tax", "0")) not in ("0", "0.00", "0.0"):
        money_line("Tax", receipt.get("tax"))
    if str(receipt.get("fees", "0")) not in ("0", "0.00", "0.0"):
        money_line("Fees", receipt.get("fees"))
    money_line("Total", receipt.get("total"), bold=True)
    money_line("Amount paid", receipt.get("amount_paid"), bold=True)
    money_line("Balance due", receipt.get("amount_due"))
    y -= 3 * mm

    payments = receipt.get("payments") or []
    if payments:
        pdf.setStrokeColor(colors.HexColor("#dddddd"))
        pdf.line(left, y, right, y)
        y -= 8 * mm
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(left, y, "Payments")
        y -= 6 * mm
        for p in payments:
            paid = p.get("paid_at") or "date unavailable"
            line(
                f"{p.get('reference', '')} ({p.get('status', '')})",
                f"{currency} {p.get('amount', '')} · {str(paid)[:19].replace('T', ' ')}",
                size=9,
                gap=5 * mm,
            )

    y -= 4 * mm
    pdf.setFont("Helvetica-Oblique", 8)
    pdf.setFillColor(colors.HexColor("#777777"))
    pdf.drawString(left, y, "This is a computer-generated receipt from J-ONE HOTEL & LODGE.")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
