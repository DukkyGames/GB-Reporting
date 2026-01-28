from __future__ import annotations

from datetime import date
from io import BytesIO
import base64
import os

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, TableStyle, Image, LongTable, Table, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader

from reports import build_report, build_report_pdf

BRAND_TEAL = colors.HexColor("#0f8da0")
BRAND_DARK = colors.HexColor("#0b6c7c")
BRAND_MUTED = colors.HexColor("#5e6c74")
LIGHT_ROW = colors.HexColor("#f4f8f9")


def _logo_path() -> str:
    return os.path.join(os.path.dirname(__file__), "static", "Logo.png")


def _make_styles():
    styles = getSampleStyleSheet()
    styles["Title"].fontSize = 20
    styles["Title"].leading = 24
    styles["Title"].textColor = BRAND_DARK
    styles.add(
        ParagraphStyle(
            "Subtitle",
            parent=styles["BodyText"],
            fontSize=10,
            leading=12,
            textColor=BRAND_MUTED,
        )
    )
    styles.add(
        ParagraphStyle(
            "Section",
            parent=styles["Heading2"],
            fontSize=12,
            leading=14,
            textColor=BRAND_DARK,
        )
    )
    return styles


def _header_story(title: str, subtitle: str | None, styles) -> list:
    story = []
    logo = _logo_path()
    if os.path.exists(logo):
        story.append(Image(logo, width=0.9 * inch, height=0.9 * inch))
    story.append(Paragraph(title, styles["Title"]))
    if subtitle:
        story.append(Paragraph(subtitle, styles["Subtitle"]))
    story.append(Spacer(1, 0.15 * inch))
    return story


def export_excel(db_path: str, start_date: date, end_date: date) -> BytesIO:
    report = build_report(db_path, start_date, end_date)
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(report["kpis"], columns=["Metric", "Value"]).to_excel(writer, sheet_name="KPIs", index=False)
        pd.DataFrame(report["table"]).to_excel(writer, sheet_name="Monthly", index=False)

    output.seek(0)
    return output


def _chart_cell(title: str, img_data: str, styles) -> Table:
    raw = base64.b64decode(img_data)
    image = Image(BytesIO(raw))
    max_width = 3.1 * inch
    max_height = 2.4 * inch
    img_w, img_h = image.imageWidth, image.imageHeight
    if img_w and img_h:
        scale = min(max_width / img_w, max_height / img_h)
        image.drawWidth = img_w * scale
        image.drawHeight = img_h * scale
    cell = Table(
        [[Paragraph(title, styles["Section"])], [image]],
        colWidths=[3.1 * inch],
        hAlign="LEFT",
    )
    cell.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return cell


def export_pdf(db_path: str, start_date: date, end_date: date) -> BytesIO:
    report = build_report_pdf(db_path, start_date, end_date)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    styles = _make_styles()

    subtitle = f"{start_date.isoformat()} to {end_date.isoformat()}"
    story = _header_story("Grimm's Bluff Sales Report", subtitle, styles)

    if report["kpis"]:
        story.append(Paragraph("Key Metrics", styles["Section"]))
        kpi_rows = [["Metric", "Value"]] + [[label, value] for label, value in report["kpis"]]
        kpi_table = _build_table(kpi_rows, col_widths=[2.6 * inch, 3.6 * inch])
        story.extend([kpi_table, Spacer(1, 0.2 * inch)])

    chart_blocks = []
    for title, key in [
        ("Monthly Net Sales", "monthly_net_sales"),
        ("Orders & Units", "orders_units"),
        ("Sales by Channel", "sales_by_channel"),
        ("Top Products by Revenue", "top_products_revenue"),
        ("Top Products by Units", "top_products_units"),
        ("Top States", "top_states"),
        ("Customer Mix", "customer_mix"),
    ]:
        img_data = report["charts"].get(key)
        if not img_data or not isinstance(img_data, str):
            continue
        chart_blocks.append(_chart_cell(title, img_data, styles))

    if chart_blocks:
        rows = []
        for idx in range(0, len(chart_blocks), 2):
            left = chart_blocks[idx]
            right = chart_blocks[idx + 1] if idx + 1 < len(chart_blocks) else ""
            rows.append([left, right])
        charts_table = Table(
            rows,
            colWidths=[3.2 * inch, 3.2 * inch],
            hAlign="LEFT",
        )
        charts_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0.1 * inch),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0.2 * inch),
                ]
            )
        )
        story.append(charts_table)
        story.append(Spacer(1, 0.2 * inch))

    if report.get("table"):
        story.append(Paragraph("Monthly Summary", styles["Section"]))
        table_rows = [["Month", "Net Sales", "Orders", "Units"]]
        for row in report["table"]:
            table_rows.append(
                [
                    str(row.get("month", "")),
                    str(row.get("net_sales", "")),
                    str(row.get("orders", "")),
                    str(row.get("units", "")),
                ]
            )
        story.append(_build_table(table_rows, col_widths=[1.2 * inch, 1.4 * inch, 1.0 * inch, 1.0 * inch]))

    doc.build(story)
    buffer.seek(0)
    return buffer


def _build_table(data: list[list[str]], col_widths: list[float] | None = None) -> LongTable:
    table = LongTable(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_TEAL),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_ROW]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def export_orders_excel(rows: list[dict]) -> BytesIO:
    output = BytesIO()
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Orders", index=False)
    output.seek(0)
    return output


def export_orders_pdf(rows: list[dict], subtitle: str | None = None) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    styles = _make_styles()

    story = _header_story("Orders", subtitle or "Current view", styles)
    if not rows:
        story.append(Paragraph("No orders in this view.", styles["BodyText"]))
    else:
        headers = ["Order #", "Completed", "Customer", "Type", "Status", "State", "Total", "Pickup"]
        table_rows = [headers]
        for row in rows:
            total = row.get("order_total")
            if isinstance(total, (int, float)):
                total_display = f"${total:,.2f}"
            else:
                total_display = str(total) if total is not None else ""
            table_rows.append(
                [
                    str(row.get("order_number", "")),
                    str(row.get("completed_date", "")),
                    str(row.get("customer", "")),
                    str(row.get("order_type", "")),
                    str(row.get("order_status", "")),
                    str(row.get("ship_state", "")),
                    total_display,
                    str(row.get("pickup", "")),
                ]
            )
        table = _build_table(
            table_rows,
            col_widths=[0.8 * inch, 0.9 * inch, 1.6 * inch, 0.8 * inch, 0.8 * inch, 0.6 * inch, 0.8 * inch, 0.6 * inch],
        )
        story.append(table)

    doc.build(story)
    buffer.seek(0)
    return buffer


def export_inventory_excel(rows: list[dict], unit: str) -> BytesIO:
    output = BytesIO()
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=f"Inventory ({unit})", index=False)
    output.seek(0)
    return output


def export_inventory_pdf(rows: list[dict], unit: str) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    styles = _make_styles()

    title = f"Inventory ({unit.title()}s)"
    story = _header_story(title, "Current view", styles)
    if not rows:
        story.append(Paragraph("No inventory rows in this view.", styles["BodyText"]))
    else:
        headers = ["SKU", "Name", "Barn", "Warehouse", "Library", "Total"]
        table_rows = [headers]
        for row in rows:
            table_rows.append(
                [
                    str(row.get("sku", "")),
                    str(row.get("name", "")),
                    f"{row.get('barn', 0):.2f}",
                    f"{row.get('warehouse', 0):.2f}",
                    f"{row.get('library', 0):.2f}",
                    f"{row.get('total', 0):.2f}",
                ]
            )
        table = _build_table(
            table_rows,
            col_widths=[1.0 * inch, 2.2 * inch, 0.8 * inch, 0.9 * inch, 0.8 * inch, 0.8 * inch],
        )
        story.append(table)

    doc.build(story)
    buffer.seek(0)
    return buffer


def export_products_excel(report: dict, start_date: date, end_date: date) -> BytesIO:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(report.get("top_skus", [])).to_excel(writer, sheet_name="Top SKUs", index=False)
        pd.DataFrame(report.get("inventory", [])).to_excel(writer, sheet_name="Inventory", index=False)
        pd.DataFrame(report.get("inventory_labels", [])).to_excel(writer, sheet_name="Inventory Labels", index=False)
        pd.DataFrame(
            [{"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "unit": report.get("unit")}]
        ).to_excel(writer, sheet_name="Filters", index=False)
    output.seek(0)
    return output


def export_products_pdf(report: dict, start_date: date, end_date: date) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    styles = _make_styles()
    unit_label = report.get("unit_label", "Units")

    subtitle = f"{start_date.isoformat()} to {end_date.isoformat()} • {unit_label}"
    story = _header_story("Products Report", subtitle, styles)

    top_skus = report.get("top_skus", [])
    if top_skus:
        headers = ["SKU", unit_label, "Avg Bottle"]
        table_rows = [headers]
        for row in top_skus:
            table_rows.append(
                [
                    str(row.get("sku", "")),
                    f"{row.get('display_qty', row.get('cases_sold', 0)):.2f}",
                    f"${row.get('avg_sale', 0):.2f}",
                ]
            )
        story.append(Paragraph("Top Selling SKUs", styles["Section"]))
        story.append(_build_table(table_rows, col_widths=[1.2 * inch, 1.0 * inch, 1.0 * inch]))
        story.append(Spacer(1, 0.2 * inch))

    inventory = report.get("inventory", [])
    if inventory:
        headers = ["SKU", unit_label]
        table_rows = [headers]
        for row in inventory:
            table_rows.append(
                [
                    str(row.get("sku", "")),
                    f"{row.get('total_inventory', 0):.2f}",
                ]
            )
        story.append(Paragraph("Inventory Available", styles["Section"]))
        story.append(_build_table(table_rows, col_widths=[1.6 * inch, 1.2 * inch]))

    doc.build(story)
    buffer.seek(0)
    return buffer


def export_tours_excel(report: dict, start_date: date, end_date: date) -> BytesIO:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(report.get("kpis", []), columns=["Metric", "Value"]).to_excel(writer, sheet_name="KPIs", index=False)
        pd.DataFrame(report.get("table", [])).to_excel(writer, sheet_name="Bookings", index=False)
        pd.DataFrame(
            [{"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}]
        ).to_excel(writer, sheet_name="Filters", index=False)
    output.seek(0)
    return output


def export_tours_pdf(report: dict, start_date: date, end_date: date) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    styles = _make_styles()

    subtitle = f"{start_date.isoformat()} to {end_date.isoformat()}"
    story = _header_story("Tour Bookings", subtitle, styles)

    if report.get("kpis"):
        story.append(Paragraph("Key Metrics", styles["Section"]))
        rows = [["Metric", "Value"]] + [[label, value] for label, value in report["kpis"]]
        story.append(_build_table(rows, col_widths=[2.6 * inch, 3.6 * inch]))
        story.append(Spacer(1, 0.2 * inch))

    if report.get("table"):
        story.append(Paragraph("Latest Bookings", styles["Section"]))
        rows = [["Date", "Experience", "Party Size", "Total Price", "Collected", "Confirmation"]]
        for row in report["table"]:
            rows.append(
                [
                    str(row.get("booking_date", "")),
                    str(row.get("experience", "")),
                    str(row.get("party_size", "")),
                    f"${row.get('total_price', 0):,.2f}",
                    f"${row.get('payment_collected', 0):,.2f}",
                    str(row.get("confirmation_code", "")),
                ]
            )
        story.append(_build_table(rows, col_widths=[0.9 * inch, 2.2 * inch, 0.8 * inch, 1.0 * inch, 1.0 * inch, 1.2 * inch]))

    doc.build(story)
    buffer.seek(0)
    return buffer
