from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Degree,
    EventFormat,
    EventType,
    GraduationYear,
    Industry,
    JobCategory,
    RecruitmentStatus,
    Sector,
)

MasterT = TypeVar("MasterT")

MASTER_MODELS = {
    "recruitment_status": RecruitmentStatus,
    "industry": Industry,
    "sector": Sector,
    "event_type": EventType,
    "event_format": EventFormat,
    "job_categories": JobCategory,
    "graduation_years": GraduationYear,
    "degrees": Degree,
}


def active_items(db: Session, model: type[MasterT]) -> list[MasterT]:
    return list(db.scalars(select(model).where(model.is_active.is_(True)).order_by(model.sort_order, model.id)))


def get_masters(db: Session) -> dict[str, list[object]]:
    return {
        "recruitment_statuses": active_items(db, RecruitmentStatus),
        "industries": active_items(db, Industry),
        "sectors": active_items(db, Sector),
        "event_types": active_items(db, EventType),
        "event_formats": active_items(db, EventFormat),
        "job_categories": active_items(db, JobCategory),
        "graduation_years": active_items(db, GraduationYear),
        "degrees": active_items(db, Degree),
    }


def sectors_for_industry(db: Session, industry: str) -> tuple[Industry | None, list[Sector]]:
    """The sector choices that are actually valid for one industry.

    get_masters returns every sector across every industry, and only the ones under the chosen
    industry pass validation, so callers preparing a write need this narrower list.
    """
    item = resolve_one(db, Industry, industry)
    if item is None:
        return None, []
    sectors = list(
        db.scalars(
            select(Sector)
            .where(Sector.industry_id == item.id, Sector.is_active.is_(True))
            .order_by(Sector.sort_order, Sector.id)
        )
    )
    return item, sectors


def resolve_one(db: Session, model: type[MasterT], value: str) -> MasterT | None:
    return db.scalar(select(model).where(model.is_active.is_(True), (model.name == value) | (model.slug == value)))


def resolve_many(db: Session, model: type[MasterT], values: list[str]) -> tuple[list[MasterT], list[str]]:
    result = list(db.scalars(select(model).where(model.is_active.is_(True), (model.name.in_(values)) | (model.slug.in_(values)))))
    matched = {item.name for item in result} | {item.slug for item in result}
    return result, [value for value in values if value not in matched]


def choices(db: Session, model: type[MasterT]) -> list[str]:
    return [item.name for item in active_items(db, model)]
