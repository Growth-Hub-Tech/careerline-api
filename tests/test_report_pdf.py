"""Day 12: the PDF skill report itself (no database)."""

import io
from datetime import UTC, datetime

from pypdf import PdfReader

from app.services.report_pdf import HistoryLine, ReportData, SubskillLine, build_report_pdf


def _data(**changes) -> ReportData:
    values = dict(
        result_id=7,
        person="Ada Learner",
        skill_name="Frontend Web Development",
        level="MID",
        score=64,
        confidence_label="high",
        answered=16,
        correct=11,
        completed_at=datetime(2026, 11, 5, 9, 30, tzinfo=UTC),
        subskills=[
            SubskillLine("HTML semantics", 4, 4, 100.0, "strong"),
            SubskillLine("React", 5, 2, 40.0, "weak"),
        ],
        strengths=["HTML semantics"],
        weaknesses=["React"],
        advice=[("React", "Build two small apps with state and effects.")],
        history=[
            HistoryLine(datetime(2026, 10, 1, tzinfo=UTC), "JUNIOR", 46),
            HistoryLine(datetime(2026, 11, 5, tzinfo=UTC), "MID", 64),
        ],
    )
    values.update(changes)
    return ReportData(**values)


def _text(content: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


def test_the_report_is_a_pdf_with_the_result():
    content = build_report_pdf(_data())
    assert content.startswith(b"%PDF")
    text = _text(content)
    for part in (
        "Frontend Web Development",
        "Ada Learner",
        "MID",
        "64",
        "HTML semantics",
        "React",
        "Build two small apps",
        "JUNIOR",
        "5 Nov 2026",
    ):
        assert part in text, part


def test_text_outside_the_basic_fonts_does_not_break_it():
    content = build_report_pdf(
        _data(person="Chidinma Ọkọ — “Ada”", advice=[("React", "Use hooks… ✓ 😀")])
    )
    text = _text(content)
    assert "Chidinma" in text and "Use hooks..." in text


def test_a_long_report_runs_onto_more_pages():
    many = [SubskillLine(f"Subskill {i}", 2, 1, 50.0, "developing") for i in range(80)]
    content = build_report_pdf(_data(subskills=many))
    assert len(PdfReader(io.BytesIO(content)).pages) > 1


def test_an_empty_history_and_no_advice_are_fine():
    content = build_report_pdf(_data(history=[], advice=[], strengths=[], weaknesses=[]))
    assert content.startswith(b"%PDF")
