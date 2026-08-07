import secrets
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


#: Crockford base32 without I, L, O and U, so a code stays unambiguous when read aloud or retyped.
PUBLIC_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
#: 8 characters carry 40 bits. Short enough that a few hundred codes fit in one transfer link.
PUBLIC_CODE_LENGTH = 8


def public_code_string() -> str:
    return "".join(secrets.choice(PUBLIC_CODE_ALPHABET) for _ in range(PUBLIC_CODE_LENGTH))


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


class CollectionTarget(Base):
    """An internal company/industry pair the operator intends to monitor."""

    __tablename__ = "collection_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    industry_id: Mapped[int] = mapped_column(ForeignKey("industries.id", ondelete="RESTRICT"), nullable=False)
    sector_id: Mapped[int | None] = mapped_column(ForeignKey("sectors.id", ondelete="RESTRICT"))
    #: This is an internal collection order, not a rating of the company. 1 is checked first.
    priority_tier: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    check_interval_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_check_result: Mapped[str | None] = mapped_column(String(32))
    last_found_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    selection_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    company: Mapped[Company] = relationship()
    industry: Mapped[Industry] = relationship()
    sector: Mapped[Sector | None] = relationship()
    sources: Mapped[list["CollectionSource"]] = relationship(
        back_populates="target", cascade="all, delete-orphan", lazy="selectin"
    )
    checks: Mapped[list["CollectionCheck"]] = relationship(back_populates="target", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("company_id", "industry_id", name="uq_collection_target_company_industry"),
        CheckConstraint("priority_tier BETWEEN 1 AND 3", name="ck_collection_target_priority"),
        CheckConstraint("check_interval_days BETWEEN 1 AND 365", name="ck_collection_target_interval"),
        CheckConstraint(
            "last_check_result IS NULL OR last_check_result IN ('found', 'no_opening', 'unreachable', 'needs_review')",
            name="ck_collection_target_result",
        ),
        Index("ix_collection_targets_queue", "is_active", "priority_tier", "next_check_at"),
    )


class CollectionSource(Base):
    __tablename__ = "collection_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_target_id: Mapped[int] = mapped_column(
        ForeignKey("collection_targets.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    target: Mapped[CollectionTarget] = relationship(back_populates="sources")

    __table_args__ = (
        UniqueConstraint("collection_target_id", "url", name="uq_collection_source_target_url"),
        CheckConstraint(
            "source_type IN ('recruit', 'internship', 'event', 'news', 'other')",
            name="ck_collection_source_type",
        ),
    )


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    #: Short public identifier used in transfer and share links, where the 36-character UUID is too bulky.
    public_code: Mapped[str] = mapped_column(
        String(PUBLIC_CODE_LENGTH), unique=True, nullable=False, default=public_code_string
    )
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    #: Shown to users as 最終更新 beside the source link, so it must mean "when the source was last
    #: read into this record". Deliberately no onupdate: a maintenance write such as the deadline
    #: sweep would silently make an unverified record look freshly checked. Only the MCP write paths
    #: in services.opportunities set this, which fails safe -- a missed bump reads as older, not newer.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
        Index("ix_opportunities_deadline", "deadline"),
        Index("ix_opportunities_filter", "status_id", "industry_id", "event_type_id"),
    )


class CollectionCheck(Base):
    """Append-only evidence of a collection attempt, including attempts that found nothing."""

    __tablename__ = "collection_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_target_id: Mapped[int] = mapped_column(
        ForeignKey("collection_targets.id", ondelete="CASCADE"), nullable=False
    )
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id", ondelete="SET NULL"))
    request_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    client_name: Mapped[str] = mapped_column(String(100), default="mcp-client", nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    target: Mapped[CollectionTarget] = relationship(back_populates="checks")
    opportunity: Mapped[Opportunity | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "result IN ('found', 'no_opening', 'unreachable', 'needs_review')",
            name="ck_collection_check_result",
        ),
    )


class CollectionRequestRecord(Base):
    """Idempotency keys for collection-target MCP writes."""

    __tablename__ = "collection_request_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


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


class OAuthClient(Base):
    """A client registered through RFC 7591 dynamic registration.

    ChatGPT and Claude mint their own client_id on first connect, so registration cannot be done by hand.
    Registration alone grants nothing: every token still comes from an operator password login.
    """

    __tablename__ = "oauth_clients"
    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: NULL for public clients, which authenticate with PKCE alone (token_endpoint_auth_method "none").
    client_secret_hash: Mapped[str | None] = mapped_column(String(64))
    client_name: Mapped[str] = mapped_column(String(200), default="unknown", nullable=False)
    redirect_uris: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    grant_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OAuthAuthorizationCode(Base):
    __tablename__ = "oauth_authorization_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str | None] = mapped_column(String(200))
    resource: Mapped[str | None] = mapped_column(String(2048))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set on first exchange. A second exchange of the same code revokes the whole grant, per OAuth 2.1.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grant_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OAuthToken(Base):
    """An issued access or refresh token, stored only as a SHA-256 hash.

    Tokens sharing a grant_id came from one authorization, so revoking the grant disconnects the client once.
    """

    __tablename__ = "oauth_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    grant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str | None] = mapped_column(String(200))
    resource: Mapped[str | None] = mapped_column(String(2048))
    #: NULL means the token never expires, which is how a refresh token keeps a client connected indefinitely.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_oauth_tokens_grant", "grant_id", "kind"),)
