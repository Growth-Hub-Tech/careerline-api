"""The PDF skill report of a result (Day 12). One row per result: its status, the PDF itself
(small, so it lives in the database: the test server's disk is wiped on every deploy) and a
version that goes up each time it is made again (older download links stop working)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ResultReport(Base):
    __tablename__ = "result_reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('generating', 'ready', 'failed')", name="ck_result_reports_status"
        ),
    )

    attempt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("test_attempt.attempt_id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="generating")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
