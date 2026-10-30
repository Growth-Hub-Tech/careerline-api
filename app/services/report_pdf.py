"""The PDF skill report of one result (Day 12), drawn with fpdf2 (pure Python).

build_report_pdf(data) -> bytes. The built-in PDF fonts only know Latin-1, so text is first
made safe: common typographic characters become their plain forms and anything else becomes
"?" (a name in another script still prints, just not every letter).
"""

from dataclasses import dataclass, field
from datetime import datetime

from fpdf import FPDF
from fpdf.enums import XPos, YPos

BRAND = "CareerLine"
INK = (33, 37, 41)
MUTED = (108, 117, 125)
ACCENT = (13, 110, 253)
BAND_COLOURS = {"strong": (25, 135, 84), "developing": (255, 153, 0), "weak": (220, 53, 69)}
PLAIN = {
    "\u2014": "-",
    "\u2013": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u2022": "-",
    "\u00a0": " ",
    "\u20a6": "NGN ",
}


@dataclass(frozen=True)
class SubskillLine:
    name: str
    answered: int
    correct: int
    percentage_score: float
    band: str


@dataclass(frozen=True)
class HistoryLine:
    completed_at: datetime
    level: str
    score: int


@dataclass
class ReportData:
    result_id: int
    person: str
    skill_name: str
    level: str
    score: int
    confidence_label: str
    answered: int
    correct: int
    completed_at: datetime
    subskills: list[SubskillLine] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    advice: list[tuple[str, str]] = field(default_factory=list)  # (subskill, advice)
    history: list[HistoryLine] = field(default_factory=list)  # oldest first


def safe(text: object) -> str:
    value = str(text)
    for fancy, plain in PLAIN.items():
        value = value.replace(fancy, plain)
    return value.encode("latin-1", "replace").decode("latin-1")


def day(moment: datetime) -> str:
    return f"{moment.day} {moment.strftime('%b %Y')}"


class _Report(FPDF):
    def __init__(self, footer_text: str):
        super().__init__(format="A4")
        self.footer_text = footer_text
        self.set_margins(18, 18, 18)
        self.set_auto_page_break(auto=True, margin=18)

    def footer(self) -> None:
        self.set_y(-13)
        self.set_font("Helvetica", size=8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, safe(f"{self.footer_text}  |  page {self.page_no()}"), align="C")


def _heading(pdf: _Report, text: str) -> None:
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 7, safe(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)


def _line(pdf: _Report, text: str, size: int = 10, style: str = "") -> None:
    pdf.set_font("Helvetica", style, size)
    pdf.multi_cell(0, 5.5, safe(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def build_report_pdf(data: ReportData) -> bytes:
    pdf = _Report(f"{BRAND} skill report  |  result {data.result_id}")
    pdf.set_title(safe(f"{BRAND} skill report: {data.skill_name}"))
    pdf.set_author(BRAND)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, safe(f"{BRAND.upper()} SKILL REPORT"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 20)
    pdf.multi_cell(0, 9, safe(data.skill_name), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    _line(pdf, f"{data.person}  |  {day(data.completed_at)}", size=11)

    _heading(pdf, "Result")
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(
        0, 9, safe(f"{data.level}  -  {data.score} / 100"), new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )
    _line(
        pdf,
        f"{data.correct} of {data.answered} questions right. Confidence in this level: "
        f"{data.confidence_label}.",
    )

    if data.subskills:
        _heading(pdf, "By subskill")
        pdf.set_font("Helvetica", "B", 9)
        widths = (88, 26, 26, 34)
        for title, width in zip(("Subskill", "Right", "Score", "Band"), widths, strict=True):
            pdf.cell(width, 6, title, border="B")
        pdf.ln()
        pdf.set_font("Helvetica", size=9)
        for line in data.subskills:
            pdf.cell(widths[0], 6, safe(line.name)[:60])
            pdf.cell(widths[1], 6, f"{line.correct}/{line.answered}")
            pdf.cell(widths[2], 6, f"{line.percentage_score:.0f}%")
            pdf.set_text_color(*BAND_COLOURS.get(line.band, INK))
            pdf.cell(widths[3], 6, safe(line.band), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(*INK)

    if data.strengths or data.weaknesses:
        _heading(pdf, "Strengths and areas to work on")
        _line(pdf, "Strengths: " + (", ".join(data.strengths) or "none yet"))
        _line(pdf, "To work on: " + (", ".join(data.weaknesses) or "none"))

    if data.advice:
        _heading(pdf, "What to do next")
        for subskill, advice in data.advice:
            _line(pdf, subskill, style="B")
            _line(pdf, advice)
            pdf.ln(1)

    if data.history:
        _heading(pdf, f"History in {data.skill_name}")
        pdf.set_font("Helvetica", size=9)
        for entry in data.history:
            pdf.cell(40, 6, day(entry.completed_at))
            pdf.cell(30, 6, safe(entry.level))
            pdf.cell(0, 6, f"{entry.score} / 100", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())
