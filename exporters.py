from __future__ import annotations

from datetime import date
from io import BytesIO
import base64

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader

from reports import build_report


def export_excel(db_path: str, start_date: date, end_date: date) -> BytesIO:
    report = build_report(db_path, start_date, end_date)
    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(report["kpis"], columns=["Metric", "Value"]).to_excel(writer, sheet_name="KPIs", index=False)
        pd.DataFrame(report["table"]).to_excel(writer, sheet_name="Monthly", index=False)

    output.seek(0)
    return output


def export_pdf(db_path: str, start_date: date, end_date: date) -> BytesIO:
    report = build_report(db_path, start_date, end_date)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    styles = getSampleStyleSheet()

    story = [Paragraph("Grimm's Bluff Sales Report", styles["Title"]), Spacer(1, 0.15 * inch)]

    kpi_table = Table(report["kpis"], colWidths=[2.4 * inch, 3.8 * inch])
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ]
        )
    )
    story.extend([kpi_table, Spacer(1, 0.2 * inch)])

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
        if not img_data:
            continue
        image = Image(ImageReader(BytesIO(base64.b64decode(img_data))), width=6.2 * inch, height=3.2 * inch)
        story.append(Paragraph(title, styles["Heading2"]))
        story.append(image)
        story.append(Spacer(1, 0.2 * inch))

    doc.build(story)
    buffer.seek(0)
    return buffer
