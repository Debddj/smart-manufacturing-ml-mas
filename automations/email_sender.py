"""
automations/email_sender.py

Email automation with PDF attachment for Supply Chain MAS.
Handles procurement smart-contract emails and final fulfillment confirmations.

Trigger 1 (send_procurement_email): ProcurementAgent if inventory insufficient.
Trigger 2 (send_fulfillment_email):  LastMileDeliveryAgent after dispatch.

.ENV variables required:
    SENDER_EMAIL     — Gmail address to send from
    SENDER_PASSWORD  — Gmail App Password (16-char, spaces allowed)
"""

from __future__ import annotations

import datetime
import hashlib
import os
import smtplib
import tempfile
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional


class EmailSender:
    """
    Handles all outbound email for the Supply Chain MAS.

    Credentials are read from environment variables (loaded via python-dotenv
    or set directly in the shell / .env file).
    """

    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587

    def __init__(self) -> None:
        self._sender_email: str = os.getenv("SENDER_EMAIL", "")
        self._sender_password: str = os.getenv("SENDER_PASSWORD", "").replace(" ", "")

    # ── PDF Generation ────────────────────────────────────────────────────────

    def generate_procurement_pdf(
        self,
        order_id: str,
        supplier_name: str,
        units: float,
        cost: float,
        delivery_days: int,
    ) -> str:
        """
        Generate a procurement smart-contract PDF and return its file path.

        The PDF includes order details, cost breakdown, delivery timeline, and a
        SHA-256 hash acting as a lightweight cryptographic proof of the contract.

        Args:
            order_id:      Unique order identifier.
            supplier_name: Name of the supplier.
            units:         Number of units procured.
            cost:          Total cost in INR.
            delivery_days: Expected delivery time in days.

        Returns:
            Absolute path to the generated PDF file.
        """
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        contract_text = (
            f"ORDER:{order_id}|SUPPLIER:{supplier_name}|UNITS:{units}|"
            f"COST:{cost}|DAYS:{delivery_days}|TS:{ts}"
        )
        contract_hash = hashlib.sha256(contract_text.encode()).hexdigest()

        pdf_path = Path(tempfile.gettempdir()) / f"procurement_{order_id}.pdf"

        try:
            from reportlab.lib.pagesizes import A4  # type: ignore
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.lib import colors
            from reportlab.platypus import (  # type: ignore
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
            )

            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=A4,
                rightMargin=2 * cm,
                leftMargin=2 * cm,
                topMargin=2.5 * cm,
                bottomMargin=2.5 * cm,
            )
            styles = getSampleStyleSheet()
            story = []

            # Title
            title_style = ParagraphStyle(
                "Title", parent=styles["Title"],
                fontSize=18, textColor=colors.HexColor("#381932"), spaceAfter=8
            )
            sub_style = ParagraphStyle(
                "Sub", parent=styles["Normal"],
                fontSize=10, textColor=colors.HexColor("#6B4A5E"), spaceAfter=4
            )
            body_style = ParagraphStyle(
                "Body", parent=styles["Normal"],
                fontSize=9, textColor=colors.HexColor("#381932"), spaceAfter=4, leading=14
            )
            hash_style = ParagraphStyle(
                "Hash", parent=styles["Normal"],
                fontSize=7, textColor=colors.HexColor("#8B6A7E"),
                fontName="Courier", spaceAfter=4, leading=10
            )

            story.append(Paragraph("Smart Manufacturing MAS", sub_style))
            story.append(Paragraph("Procurement Smart Contract", title_style))
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E8D5C4")))
            story.append(Spacer(1, 0.4 * cm))

            # Contract table
            table_data = [
                ["Field", "Value"],
                ["Order ID", order_id],
                ["Issued At", ts],
                ["Supplier", supplier_name],
                ["Units Procured", f"{units:.0f} units"],
                ["Unit Cost (INR)", f"₹ {cost / max(units, 1):.2f}"],
                ["Total Cost (INR)", f"₹ {cost:,.2f}"],
                ["Expected Delivery", f"{delivery_days} business days"],
                ["Contract Status", "CONFIRMED"],
            ]

            tbl = Table(table_data, colWidths=[5 * cm, 11 * cm])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#381932")),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, 0), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.HexColor("#FFFBF7"), colors.HexColor("#FFF3E6")]),
                ("FONTSIZE",   (0, 1), (-1, -1), 9),
                ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#E8D5C4")),
                ("LEFTPADDING",  (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING",   (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 0.5 * cm))

            # Terms
            story.append(Paragraph("<b>Terms & Conditions</b>", body_style))
            story.append(Paragraph(
                "1. Payment due within 30 days of delivery. "
                "2. Goods must match specifications; reject non-conforming items. "
                "3. Force-majeure clause applies for supply disruptions exceeding 7 days. "
                "4. Disputes resolved under Mumbai Arbitration Centre.",
                body_style,
            ))
            story.append(Spacer(1, 0.4 * cm))

            # Cryptographic hash
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E8D5C4")))
            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph("<b>Contract Hash (SHA-256)</b>", hash_style))
            story.append(Paragraph(contract_hash, hash_style))
            story.append(Paragraph(
                "This hash uniquely identifies the contract parameters. "
                "Verify integrity by recomputing SHA-256 of the contract fields.",
                hash_style,
            ))

            doc.build(story)
            print(f"[EMAIL] [PDF] Generated procurement PDF: {pdf_path}")
            return str(pdf_path)

        except ImportError:
            # Fallback: write a plain-text pseudo-PDF
            with open(pdf_path, "w", encoding="utf-8") as f:
                f.write(f"Procurement Contract\n{'='*40}\n")
                f.write(f"Order ID:     {order_id}\n")
                f.write(f"Supplier:     {supplier_name}\n")
                f.write(f"Units:        {units}\n")
                f.write(f"Total Cost:   ₹{cost:,.2f}\n")
                f.write(f"Delivery:     {delivery_days} days\n")
                f.write(f"Issued:       {ts}\n")
                f.write(f"Hash:         {contract_hash}\n")
            print(f"[EMAIL] [PDF] reportlab not installed — wrote text fallback: {pdf_path}")
            return str(pdf_path)

        except Exception as exc:
            print(f"[EMAIL] [PDF ERROR] {exc}")
            # Return empty path on failure
            return ""

    # ── Send procurement email ────────────────────────────────────────────────

    def send_procurement_email(
        self,
        order_id: str,
        supplier_name: str,
        units: float,
        cost: float,
        delivery_days: int,
        recipient_email: str = "adityabhowmik68@gmail.com",
    ) -> bool:
        """
        Send a procurement smart-contract email with a PDF attachment.

        Args:
            order_id:        Unique order identifier.
            supplier_name:   Name of the supplier.
            units:           Units procured.
            cost:            Total procurement cost (INR).
            delivery_days:   Expected delivery time.
            recipient_email: Destination address (defaults to configured address).

        Returns:
            True on success, False on failure.
        """
        subject = f"Smart Contract - Order {order_id}"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = f"""
Dear Supply Chain Team,

A new procurement contract has been raised by the Smart Manufacturing MAS.

─────────────────────────────────────────
ORDER DETAILS
─────────────────────────────────────────
Order ID       : {order_id}
Supplier       : {supplier_name}
Units Ordered  : {units:.0f}
Total Cost     : ₹{cost:,.2f}
Unit Price     : ₹{cost / max(units, 1):.2f}
Est. Delivery  : {delivery_days} business days
Issued At      : {ts}
─────────────────────────────────────────

Please review the attached PDF contract and acknowledge receipt within 24 hours.

This is an automated message from the Smart Manufacturing Multi-Agent System.
        """.strip()

        print(f"[EMAIL] Sending procurement email to {recipient_email} | Subject: {subject}")

        try:
            pdf_path = self.generate_procurement_pdf(
                order_id, supplier_name, units, cost, delivery_days
            )

            msg = MIMEMultipart()
            msg["From"] = self._sender_email
            msg["To"] = recipient_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            if pdf_path and Path(pdf_path).exists():
                with open(pdf_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="procurement_{order_id}.pdf"',
                )
                msg.attach(part)

            with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT) as server:
                server.starttls()
                server.login(self._sender_email, self._sender_password)
                server.sendmail(self._sender_email, recipient_email, msg.as_string())

            print(f"[EMAIL] ✓ Procurement email sent to {recipient_email}")
            return True

        except Exception as exc:
            print(f"[EMAIL] [ERROR] Failed to send procurement email: {exc}")
            return False

    # ── Send fulfillment email ────────────────────────────────────────────────

    def generate_invoice_pdf(
        self,
        order_id: str,
        delivered_units: float = 100.0,
        cart_units: int = 0,
        context: str = "Summer",
    ) -> str:
        """
        Generate a customer-facing supplier invoice PDF for the fulfilled order.

        Args:
            order_id:        Unique order identifier.
            delivered_units: Units delivered to the customer (warehouse-dispatched).
            cart_units:      Number of items in the original cart.
            context:         Environment context (Summer / Winter).

        Returns:
            Absolute path to the generated PDF, or "" on failure.
        """
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        unit_price = 1250.0
        total      = delivered_units * unit_price
        inv_no     = "INV-" + order_id.replace("ORD-", "")
        hash_val   = hashlib.sha256(f"{order_id}{ts}{total}".encode()).hexdigest()[:24]

        pdf_path = Path(tempfile.gettempdir()) / f"invoice_{order_id}.pdf"

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import cm
            from reportlab.lib import colors
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
            )

            doc = SimpleDocTemplate(
                str(pdf_path), pagesize=A4,
                rightMargin=2*cm, leftMargin=2*cm,
                topMargin=2.5*cm, bottomMargin=2.5*cm,
            )
            styles = getSampleStyleSheet()

            H1 = ParagraphStyle("H1", parent=styles["Title"],
                                fontSize=20, textColor=colors.HexColor("#381932"), spaceAfter=4)
            SUB = ParagraphStyle("SUB", parent=styles["Normal"],
                                 fontSize=9, textColor=colors.HexColor("#6B4A5E"), spaceAfter=2)
            BODY = ParagraphStyle("BODY", parent=styles["Normal"],
                                  fontSize=9, textColor=colors.HexColor("#381932"),
                                  spaceAfter=4, leading=14)
            MONO = ParagraphStyle("MONO", parent=styles["Normal"],
                                  fontSize=7, fontName="Courier",
                                  textColor=colors.HexColor("#8B6A7E"), spaceAfter=3, leading=10)

            story = []

            # ── Header ──────────────────────────────────────────────────────────
            story.append(Paragraph("Smart Manufacturing MAS", SUB))
            story.append(Paragraph("Customer Invoice", H1))
            story.append(HRFlowable(width="100%", thickness=1.5,
                                    color=colors.HexColor("#381932")))
            story.append(Spacer(1, 0.3*cm))

            # Meta row
            meta = Table(
                [["Invoice No.", inv_no, "Date", ts],
                 ["Order ID",   order_id, "Context", context]],
                colWidths=[3.5*cm, 6*cm, 2.5*cm, 5*cm]
            )
            meta.setStyle(TableStyle([
                ("FONTSIZE",  (0,0), (-1,-1), 8),
                ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#6B4A5E")),
                ("TEXTCOLOR", (2,0), (2,-1), colors.HexColor("#6B4A5E")),
                ("FONTNAME",  (0,0), (0,-1), "Helvetica-Bold"),
                ("FONTNAME",  (2,0), (2,-1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ]))
            story.append(meta)
            story.append(Spacer(1, 0.4*cm))

            # ── Line items ──────────────────────────────────────────────────────
            story.append(Paragraph("<b>Order Line Items</b>", BODY))
            display_qty = cart_units if cart_units > 0 else delivered_units
            items = [
                ["Description", "Cart Qty", "Delivered", "Unit Price (₹)", "Total (₹)"],
                ["Supply Chain Goods — MAS Fulfillment",
                 f"{int(display_qty)}",
                 f"{delivered_units:.0f}",
                 f"{unit_price:,.2f}",
                 f"{total:,.2f}"],
                ["Express Logistics Handling", "1", "1", "500.00", "500.00"],
                ["Quality Assurance Fee",      "1", "1", "250.00", "250.00"],
            ]
            grand_total = total + 500 + 250

            tbl = Table(items, colWidths=[6.5*cm, 1.8*cm, 1.8*cm, 3*cm, 3*cm])
            tbl.setStyle(TableStyle([
                ("BACKGROUND",   (0,0), (-1,0), colors.HexColor("#381932")),
                ("TEXTCOLOR",    (0,0), (-1,0), colors.white),
                ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
                ("FONTSIZE",     (0,0), (-1,-1), 9),
                ("ALIGN",        (1,0), (-1,-1), "RIGHT"),
                ("ROWBACKGROUNDS",(0,1),(-1,-1),
                 [colors.HexColor("#FFFBF7"), colors.HexColor("#FFF3E6")]),
                ("GRID",         (0,0), (-1,-1), 0.5, colors.HexColor("#E8D5C4")),
                ("LEFTPADDING",  (0,0), (-1,-1), 8),
                ("RIGHTPADDING", (0,0), (-1,-1), 8),
                ("TOPPADDING",   (0,0), (-1,-1), 5),
                ("BOTTOMPADDING",(0,0), (-1,-1), 5),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 0.25*cm))

            # Total row
            total_tbl = Table(
                [["", "Sub-total", f"₹{total+500+250-grand_total+grand_total:,.2f}"],
                 ["", "GST (18%)", f"₹{grand_total*0.18:,.2f}"],
                 ["", "GRAND TOTAL", f"₹{grand_total*1.18:,.2f}"]],
                colWidths=[8*cm, 3.5*cm, 5.5*cm]
            )
            total_tbl.setStyle(TableStyle([
                ("FONTSIZE",  (0,0), (-1,-1), 9),
                ("ALIGN",     (1,0), (-1,-1), "RIGHT"),
                ("FONTNAME",  (1,2), (-1,2), "Helvetica-Bold"),
                ("BACKGROUND",(1,2), (-1,2), colors.HexColor("#381932")),
                ("TEXTCOLOR", (1,2), (-1,2), colors.white),
                ("TOPPADDING",   (0,0), (-1,-1), 4),
                ("BOTTOMPADDING",(0,0), (-1,-1), 4),
            ]))
            story.append(total_tbl)
            story.append(Spacer(1, 0.5*cm))

            # ── Footer ──────────────────────────────────────────────────────────
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=colors.HexColor("#E8D5C4")))
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph("<b>Payment Terms:</b> Net 30 days from invoice date. "
                                   "Bank transfer to Smart MAS Escrow Account.", BODY))
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph(f"<b>Invoice Hash:</b> {hash_val}", MONO))
            story.append(Paragraph(
                "This is a computer-generated invoice from the Smart Manufacturing "
                "Multi-Agent System. No signature required.", MONO))

            doc.build(story)
            print(f"[EMAIL] [PDF] Generated invoice PDF: {pdf_path}")
            return str(pdf_path)

        except Exception as exc:
            print(f"[EMAIL] [PDF ERROR] Invoice generation failed: {exc}")
            return ""

    def send_fulfillment_email(
        self,
        order_id: str,
        recipient_email: str = "adityabhowmik68@gmail.com",
        delivered_units: float = 100.0,
        cart_units: int = 0,
        context: str = "Summer",
    ) -> bool:
        """
        Send order confirmation email with a PDF invoice attached.
        Fires on EVERY fulfilled order (Branch A, B, or C).

        Args:
            order_id:        The dispatched order.
            recipient_email: Destination address.
            delivered_units: Units delivered (from warehouse dispatch).
            cart_units:      Items originally in the cart.
            context:         Environment context for the invoice.

        Returns:
            True on success, False on failure.
        """
        display_ordered = cart_units if cart_units > 0 else int(delivered_units)
        subject  = f"✅ Order Confirmed & Dispatched — {order_id}"
        ts       = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inv_no   = "INV-" + order_id.replace("ORD-", "")
        unit_price = 1250.0
        subtotal   = delivered_units * unit_price
        gst        = (subtotal + 750) * 0.18
        grand      = subtotal + 750 + gst

        body = f"""Dear Customer,

Your order has been fulfilled and dispatched by the Smart Manufacturing MAS.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ORDER SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Order ID       : {order_id}
Invoice No.    : {inv_no}
Items Ordered  : {display_ordered} item(s)
Units Delivered: {delivered_units:.0f}
Context        : {context}
Dispatched At  : {ts}

Amount Summary:
  Sub-total    : ₹{subtotal + 750:,.2f}
  GST (18%)    : ₹{gst:,.2f}
  Grand Total  : ₹{grand:,.2f}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Your full invoice with line-item breakdown is attached as a PDF.
Expected delivery: 2–3 business days.

Thank you for using Smart Manufacturing MAS.
— Automated Dispatch System""".strip()

        print(f"[EMAIL] Sending fulfillment+invoice email to {recipient_email} | {order_id}")

        try:
            # ── Generate invoice PDF ─────────────────────────────────────────────
            pdf_path = self.generate_invoice_pdf(
                order_id=order_id,
                delivered_units=delivered_units,
                cart_units=cart_units,
                context=context,
            )

            msg = MIMEMultipart()
            msg["From"]    = self._sender_email
            msg["To"]      = recipient_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            # Attach invoice PDF
            if pdf_path and Path(pdf_path).exists():
                with open(pdf_path, "rb") as f:
                    part = MIMEBase("application", "pdf")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="Invoice_{order_id}.pdf"',
                )
                msg.attach(part)
                print(f"[EMAIL] [PDF] Attached invoice: Invoice_{order_id}.pdf")

            with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT) as server:
                server.starttls()
                server.login(self._sender_email, self._sender_password)
                server.sendmail(self._sender_email, recipient_email, msg.as_string())

            print(f"[EMAIL] ✓ Fulfillment+invoice email sent to {recipient_email}")
            return True

        except Exception as exc:
            print(f"[EMAIL] [ERROR] Failed to send fulfillment email: {exc}")
            return False


