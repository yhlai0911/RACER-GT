from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]


def register_fonts() -> tuple[str, str]:
    candidates = [
        ("NotoSansCJK", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for family, regular, bold in candidates:
        if Path(regular).exists():
            pdfmetrics.registerFont(TTFont(family, regular))
            if Path(bold).exists():
                pdfmetrics.registerFont(TTFont(f"{family}-Bold", bold))
                return family, f"{family}-Bold"
            return family, family
    return "Helvetica", "Helvetica-Bold"


def clean_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
    text = text.replace("&", "&amp;").replace("<font", "@@FONT").replace("</font>", "@@ENDFONT")
    text = text.replace("<b>", "@@B").replace("</b>", "@@ENDB").replace("<i>", "@@I").replace("</i>", "@@ENDI")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return (text.replace("@@FONT", "<font").replace("@@ENDFONT", "</font>")
                .replace("@@B", "<b>").replace("@@ENDB", "</b>")
                .replace("@@I", "<i>").replace("@@ENDI", "</i>"))


def build(markdown: Path, output: Path, language: str) -> None:
    regular, bold = register_fonts()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName=regular, fontSize=9.5, leading=14, spaceAfter=5)
    title = ParagraphStyle("Title", parent=styles["Title"], fontName=bold, fontSize=21, leading=26, alignment=TA_CENTER, spaceAfter=16)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName=bold, fontSize=15, leading=19, spaceBefore=10, spaceAfter=7)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName=bold, fontSize=12, leading=16, spaceBefore=8, spaceAfter=5)
    code = ParagraphStyle("Code", parent=body, fontName="Courier", fontSize=7.5, leading=10, leftIndent=6 * mm, backColor="#f3f3f3")
    bullet = ParagraphStyle("Bullet", parent=body, leftIndent=7 * mm, firstLineIndent=-3 * mm)

    lines = markdown.read_text(encoding="utf-8").splitlines()
    story = []
    in_code = False
    code_lines: list[str] = []
    first_title = True

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                story.append(Paragraph("<br/>".join(clean_inline(x) for x in code_lines), code))
                story.append(Spacer(1, 3 * mm))
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line or " ")
            continue
        if not line:
            story.append(Spacer(1, 2 * mm))
        elif line.startswith("# "):
            if not first_title:
                story.append(PageBreak())
            story.append(Paragraph(clean_inline(line[2:]), title if first_title else h1))
            if first_title:
                subtitle = "Methodology, identification, diagnostics, and reproducible implementation" if language == "en" else "研究方法、識別、診斷與可重現實作"
                story.append(Paragraph(subtitle, ParagraphStyle("Subtitle", parent=body, alignment=TA_CENTER, fontSize=10.5)))
            first_title = False
        elif line.startswith("## "):
            story.append(Paragraph(clean_inline(line[3:]), h1))
        elif line.startswith("### "):
            story.append(Paragraph(clean_inline(line[4:]), h2))
        elif re.match(r"^[-*] ", line):
            story.append(Paragraph("• " + clean_inline(line[2:]), bullet))
        elif re.match(r"^\d+\. ", line):
            story.append(Paragraph(clean_inline(line), bullet))
        elif line.startswith("|"):
            story.append(Paragraph(clean_inline(line), code))
        else:
            story.append(Paragraph(clean_inline(line), body))

    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title="RACER-GT Methodology", author="Yi-Hao Lai")
    doc.build(story)


if __name__ == "__main__":
    build(ROOT / "docs/en/METHODOLOGY.md", ROOT / "docs/en/RACER_GT_Methodology_en.pdf", "en")
    build(ROOT / "docs/zh-TW/METHODOLOGY.md", ROOT / "docs/zh-TW/RACER_GT_Methodology_zh_TW.pdf", "zh-TW")
