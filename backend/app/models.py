import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def uuid_string() -> str:
    return str(uuid.uuid4())


class NamedMasterMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class Industry(NamedMasterMixin, Base):
    __tablename__ = "industries"
    sectors: Mapped[list["Sector"]] = relationship(back_populates="industry")


class Sector(NamedMasterMixin, Base):
    __tablename__ = "sectors"
    industry_id: Mapped[int] = mapped_column(ForeignKey("industries.id", ondelete="RESTRICT"), nullable=False)
    industry: Mapped[Industry] = relationship(back_populates="sectors")
    __table_args__ = (UniqueConstraint("industry_id", "name", name="uq_sector_industry_name"),)


class JobCategory(NamedMasterMixin, Base):
    __tablename__ = "job_categories"


class GraduationYear(NamedMasterMixin, Base):
    __tablename__ = "graduation_years"


class Degree(NamedMasterMixin, Base):
    __tablename__ = "degrees"


class RecruitmentStatus(NamedMasterMixin, Base):
    __tablename__ = "recruitment_statuses"


class EventType(NamedMasterMixin, Base):
    __tablename__ = "event_types"


class EventFormat(NamedMasterMixin, Base):
    __tablename__ = "event_formats"


opportunity_jobs = Table(
    "opportunity_jobs",
    Base.metadata,
    Column("opportunity_id", String(36), ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True),
    Column("job_category_id", Integer, ForeignKey("job_categories.id", ondelete="RESTRICT"), primary_key=True),
)
opportunity_graduation_years = Table(
    "opportunity_graduation_years",
    Base.metadata,
    Column("opportunity_id", String(36), ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True),
    Column("graduation_year_id", Integer, ForeignKey("graduation_years.id", ondelete="RESTRICT"), primary_key=True),
)
opportunity_degrees = Table(
    "opportunity_degrees",
    Base.metadata,
    Column("opportunity_id", String(36), ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True),
    Column("degree_id", Integer, ForeignKey("degrees.id", ondelete="RESTRICT"), primary_key=True),
)
opportunity_tags = Table(
    "opportunity_tags",
    Base.metadata,
    Column("opportunity_id", String(36), ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="RESTRICT"), primary_key=True),
)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    status_id: Mapped[int] = mapped_column(ForeignKey("recruitment_statuses.id", ondelete="RESTRICT"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    industry_id: Mapped[int] = mapped_column(ForeignKey("industries.id", ondelete="RESTRICT"), nullable=False)
    sector_id: Mapped[int] = mapped_column(ForeignKey("sectors.id", ondelete="RESTRICT"), nullable=False)
    event_type_id: Mapped[int] = mapped_column(ForeignKey("event_types.id", ondelete="RESTRICT"), nullable=False)
    event_format_id: Mapped[int] = mapped_column(ForeignKey("event_formats.id", ondelete="RESTRICT"), nullable=False)

    event_name: Mapped[str] = mapped_column(String(100), nullable=False)
    deadline: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(String(300))
    selection_process: Mapped[str | None] = mapped_column(String(1000))
    homepage_url: Mapped[str | None] = mapped_column(String(2048))
    event_start_date: Mapped[date | None] = mapped_column(Date)
    event_end_date: Mapped[date | None] = mapped_column(Date)
    period_note: Mapped[str | None] = mapped_column(String(200))
    requirements: Mapped[str | None] = mapped_column(String(1000))
    compensation: Mapped[str | None] = mapped_column(String(500))
    audience_note: Mapped[str | None] = mapped_column(String(200))
    recruitment_start_date: Mapped[date | None] = mapped_column(Date)
    entry_url: Mapped[str | None] = mapped_column(String(2048))
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    company_rating: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    status: Mapped[RecruitmentStatus] = relationship()
    company: Mapped[Company] = relationship()
    industry: Mapped[Industry] = relationship()
    sector: Mapped[Sector] = relationship()
    event_type: Mapped[EventType] = relationship()
    event_format: Mapped[EventFormat] = relationship()
    job_categories: Mapped[list[JobCategory]] = relationship(secondary=opportunity_jobs, lazy="selectin")
    graduation_years: Mapped[list[GraduationYear]] = relationship(
        secondary=opportunity_graduation_years, lazy="selectin"
    )
    degrees: Mapped[list[Degree]] = relationship(secondary=opportunity_degrees, lazy="selectin")
    tags: Mapped[list[Tag]] = relationship(secondary=opportunity_tags, lazy="selectin")

    __table_args__ = (
        CheckConstraint("event_end_date IS NULL OR event_start_date IS NULL OR event_end_date >= event_start_date", name="ck_event_dates"),
        CheckConstraint("deadline IS NULL OR recruitment_start_date IS NULL OR deadline >= recruitment_start_date", name="ck_recruitment_dates"),
        CheckConstraint("company_rating IS NULL OR company_rating BETWEEN 1 AND 5", name="ck_company_rating"),
        Index("ix_opportunities_deadline", "deadline"),
        Index("ix_opportunities_filter", "status_id", "industry_id", "event_type_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(100), index=True)
    client_name: Mapped[str] = mapped_column(String(100), default="unknown", nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    success: Mapped[bool] = mapped_column(nullable=False)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False)
    response_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
