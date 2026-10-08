from fastapi import APIRouter, HTTPException, Query

from app.dates import today_in_tokyo
from app.db import DbSession
from app.schemas import CompanyDetailResponse, CompanyListResponse
from app.services.companies import get_company_by_public_code
from app.services.company_pages import (
    company_detail_dict,
    company_summary_dict,
    get_company_page,
    list_indexable_companies,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=CompanyListResponse)
def list_companies(
    db: DbSession,
    indexable: bool = Query(
        default=True,
        description="プロフィールが登録済みの企業だけを返す。現在はtrueのみ対応。",
    ),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    # Only the indexable set has a public listing use today: it is what the sitemap needs. Every
    # other company is reachable through its own page, so a broader listing would just be a
    # crawlable index of pages we deliberately keep out of search.
    if not indexable:
        raise HTTPException(status_code=400, detail="indexable=falseはまだ対応していません")
    result = list_indexable_companies(db, today=today_in_tokyo(), page=page, per_page=per_page)
    return {
        "items": [
            company_summary_dict(
                item.company,
                current_opportunity_count=item.current_opportunity_count,
                openings_updated_at=item.openings_updated_at,
            )
            for item in result.items
        ],
        "total": result.total,
        "page": result.page,
        "per_page": result.per_page,
        "total_pages": result.total_pages,
    }


@router.get("/{public_code}", response_model=CompanyDetailResponse)
def company_detail(public_code: str, db: DbSession) -> dict[str, object]:
    company = get_company_by_public_code(db, public_code)
    if company is None:
        raise HTTPException(status_code=404, detail="企業情報が見つかりません")
    return company_detail_dict(get_company_page(db, company, today=today_in_tokyo()))
