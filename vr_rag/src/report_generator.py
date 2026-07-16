"""
Quiz report generator for the Dr. Raggy clinical training simulator.
Takes the user's end-of-session quiz results and produces a styled PDF report
showing per-patient and overall recall scores. Used by the /report endpoint.
The PDF is written to a reports directory and the path is returned to the
caller (Unity), which then fetches the file for download / display.
"""

import os
import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)


# Where generated reports are saved. Created on first use.
REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"


def _ensure_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def generate_report_pdf(results: list, session_id: str = None) -> str:
    """
    Build a PDF from quiz results.

    `results` is a list of per-patient dicts:
        [
          {"patientId": "P1101", "correct": 3, "total": 4},
          {"patientId": "P1102", "correct": 4, "total": 4},
          ...
        ]

    Returns the absolute path to the generated PDF.
    """
    reports_dir = _ensure_reports_dir()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_session = (session_id or "session")[:8]
    filename = f"handover_report_{safe_session}_{timestamp}.pdf"
    filepath = reports_dir / filename

    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=22,
        textColor=colors.HexColor("#1a4d6e"),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#666666"),
        spaceAfter=18,
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=14,
        textColor=colors.HexColor("#1a4d6e"),
        spaceBefore=12,
        spaceAfter=8,
    )

    story = []

    # ---- Header ----
    story.append(Paragraph("Clinical Handover Recall Report", title_style))
    timestamp_human = datetime.datetime.now().strftime("%d %B %Y, %H:%M")
    story.append(Paragraph(
        f"Dr. Raggy Training Simulator &nbsp;|&nbsp; Generated {timestamp_human}",
        subtitle_style,
    ))

    # ---- Compute totals ----
    total_correct = sum(r.get("correct", 0) for r in results)
    total_questions = sum(r.get("total", 0) for r in results)
    pct = (100.0 * total_correct / total_questions) if total_questions else 0.0

    # ---- Overall summary box ----
    story.append(Paragraph("Overall Performance", heading_style))
    summary_data = [
        ["Patients reviewed", str(len(results))],
        ["Questions answered", str(total_questions)],
        ["Correct answers", str(total_correct)],
        ["Overall score", f"{pct:.0f}%"],
    ]
    summary_table = Table(summary_data, colWidths=[7 * cm, 7 * cm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f7")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#222222")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 18))

    # ---- Per-patient breakdown ----
    story.append(Paragraph("Per-Patient Breakdown", heading_style))

    table_data = [["Patient", "Score", "Result"]]
    for r in results:
        pid = r.get("patientId", "(unknown)")
        correct = r.get("correct", 0)
        total = r.get("total", 0)
        patient_pct = (100.0 * correct / total) if total else 0.0
        verdict = "Pass" if patient_pct >= 75 else "Review"
        table_data.append([pid, f"{correct} / {total}", f"{patient_pct:.0f}% — {verdict}"])

    breakdown = Table(table_data, colWidths=[5 * cm, 4 * cm, 5 * cm])
    breakdown.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a4d6e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
            [colors.white, colors.HexColor("#f6f9fb")]),
    ]))
    story.append(breakdown)
    story.append(Spacer(1, 24))

    # ---- Footer note ----
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#999999"),
    )
    story.append(Paragraph(
        "This report reflects recall accuracy during a simulated clinical "
        "handover exercise. It is a training aid only and is not a clinical "
        "record.",
        footer_style,
    ))

    doc.build(story)
    return str(filepath)