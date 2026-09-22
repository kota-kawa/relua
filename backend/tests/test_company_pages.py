from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.api.companies import company_detail, list_companies
from app.dates import today_in_tokyo
from app.schemas import OpportunityInput
from app.services.companies import get_or_create_company, update_company_profile
from app.services.company_pages import (
    company_detail_dict,
    get_company_page,
    list_indexable_companies,
)
from app.services.opportunities import write_opportunity
from tests.test_validation import valid_payload

#: Long enough to satisfy the enforced minimums, so these tests exercise the page rules rather than
#: the input validation covered in test_companies.py.
SUMMARY = "産業用センサーを開発し、国内の製造業向けに販売している架空企業です。"
DESCRIPTION = "自社工場でセンサーを設計・製造し、制御ソフトウェアと組み合わせて提供しています。" * 5


def profiled_company(db, name: str, *, profile: dict | None = None):
    """A company with a complete profile unless the test asks for something narrower."""
    company = get_or_create_company(db, name)
    db.flush()
    changes = {"business_summary": SUMMARY, "description": DESCRIPTION} if profile is None else profile
    if changes:
        update_company_profile(
            db,
            company_id=company.id,
            changes=changes,
            source_url="https://example.com/company/",
            request_id=f"profile-{company.id}",
            client_name="pytest",
        )
    return company


def posting(db, company_name: str, *, request_id: str, **overrides):
    # A distinct event name per posting: same company plus same event identity is an exact duplicate
    # and would be rejected by the write path.
    payload = valid_payload() | {"company_name": company_name, "event_name": f"募集 {request_id}"} | overrides
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(payload),
        request_id=request_id,
        client_name="pytest",
    )
    return item


def test_company_page_splits_current_openings_from_finished_ones(db):
    today = today_in_tokyo()
    company = profiled_company(db, "株式会社カレント")
    open_soon = posting(
        db,
        company.name,
        request_id="page-open-1",
        deadline=(today + timedelta(days=3)).isoformat(),
        source_url="https://example.com/open-soon",
    )
    open_later = posting(
        db,
        company.name,
        request_id="page-open-2",
        deadline=(today + timedelta(days=40)).isoformat(),
        source_url="https://example.com/open-later",
    )
    # No deadline at all is still current: it sorts after every dated posting.
    undated = posting(
        db,
        company.name,
        request_id="page-open-3",
        recruitment_status="通年募集",
        deadline=None,
        source_url="https://example.com/undated",
    )
    closed = posting(
        db,
        company.name,
        request_id="page-closed-1",
        recruitment_status="締切",
        deadline=(today - timedelta(days=5)).isoformat(),
        source_url="https://example.com/closed",
    )
    # Today's deadline has not passed yet, so it belongs to the current side of the split.
    due_today = posting(
        db,
        company.name,
        request_id="page-open-4",
        deadline=today.isoformat(),
        source_url="https://example.com/due-today",
    )

    page = get_company_page(db, company, today=today)

    assert [item.id for item in page.current] == [due_today.id, open_soon.id, open_later.id, undated.id]
    assert [item.id for item in page.past] == [closed.id]

    payload = company_detail_dict(page)
    assert payload["current_opportunity_count"] == 4
    assert payload["public_code"] == company.public_code
    assert payload["url"].endswith(f"/companies/{company.public_code}")
    assert [item["id"] for item in payload["past_opportunities"]] == [closed.id]
    # Finished postings count towards the date as well: they are on the page, and leaving them out
    # would move it backwards on the day a company's last current opening expires.
    assert payload["openings_updated_at"] == max(item.updated_at for item in page.current + page.past)


def test_a_posting_whose_deadline_passed_while_still_marked_open_is_not_current(db):
    today = today_in_tokyo()
    company = profiled_company(db, "株式会社ステイル")
    stale = posting(
        db,
        company.name,
        request_id="page-stale-1",
        deadline=(today - timedelta(days=1)).isoformat(),
        source_url="https://example.com/stale",
    )

    page = get_company_page(db, company, today=today)
    assert page.current == []
    assert [item.id for item in page.past] == [stale.id]


def test_indexable_listing_requires_a_full_profile(db):
    today = today_in_tokyo()
    profiled_and_open = profiled_company(db, "株式会社アイ")
    posting(db, profiled_and_open.name, request_id="idx-1", source_url="https://example.com/idx-1")

    unprofiled = profiled_company(db, "株式会社ハー", profile={})
    posting(db, unprofiled.name, request_id="idx-3", source_url="https://example.com/idx-3")

    # A lead without a body, and a body without a lead, are both incomplete.
    summary_only = profiled_company(db, "株式会社ニー", profile={"business_summary": SUMMARY})
    posting(db, summary_only.name, request_id="idx-4", source_url="https://example.com/idx-4")

    body_only = profiled_company(db, "株式会社ホー", profile={"description": DESCRIPTION})
    posting(db, body_only.name, request_id="idx-5", source_url="https://example.com/idx-5")

    blank = profiled_company(db, "株式会社ヘー")
    blank.business_summary = "   "
    db.flush()
    posting(db, blank.name, request_id="idx-6", source_url="https://example.com/idx-6")

    result = list_indexable_companies(db, today=today)

    assert [item.company.id for item in result.items] == [profiled_and_open.id]
    assert result.total == 1
    assert result.items[0].current_opportunity_count == 1
    assert result.items[0].openings_updated_at is not None


def test_a_described_company_stays_listed_after_its_last_opening_ends(db):
    """The profile is the reason the page exists, so it does not leave the index with the postings.

    The listed last-modified date has to keep spanning the finished postings too: taken from the
    current openings alone it would jump back to the profile date the day the last one expired.
    """
    today = today_in_tokyo()
    closed = profiled_company(db, "株式会社ロー")
    finished = posting(
        db,
        closed.name,
        request_id="idx-2",
        recruitment_status="締切",
        deadline=(today - timedelta(days=2)).isoformat(),
        source_url="https://example.com/idx-2",
    )
    never_posted = profiled_company(db, "株式会社ワン")

    result = list_indexable_companies(db, today=today)
    listed = {item.company.id: item for item in result.items}

    assert result.total == 2
    assert listed[closed.id].current_opportunity_count == 0
    # Compared without tzinfo: the aggregate reads the column straight back, and SQLite returns it
    # naive where the mapped attribute is aware.
    assert listed[closed.id].openings_updated_at.replace(tzinfo=None) == finished.updated_at.replace(tzinfo=None)
    assert listed[never_posted.id].current_opportunity_count == 0
    assert listed[never_posted.id].openings_updated_at is None


def test_listed_opening_count_excludes_the_finished_postings_it_shares_a_company_with(db):
    """The aggregate stopped filtering rows when it started including finished ones.

    Current openings are now separated by a CASE inside the count instead, so a company holding
    both kinds is the case that tells the two apart.
    """
    today = today_in_tokyo()
    company = profiled_company(db, "株式会社マゼ")
    posting(db, company.name, request_id="mixed-open", source_url="https://example.com/mixed-open")
    posting(
        db,
        company.name,
        request_id="mixed-closed",
        recruitment_status="締切",
        deadline=(today - timedelta(days=4)).isoformat(),
        source_url="https://example.com/mixed-closed",
    )

    result = list_indexable_companies(db, today=today)

    assert [item.company.id for item in result.items] == [company.id]
    assert result.items[0].current_opportunity_count == 1


def test_indexable_listing_pages_through_results_without_repeating_companies(db):
    today = today_in_tokyo()
    for index in range(5):
        company = profiled_company(db, f"株式会社ページ{index}")
        posting(db, company.name, request_id=f"paging-{index}", source_url=f"https://example.com/paging-{index}")

    first = list_indexable_companies(db, today=today, page=1, per_page=2)
    second = list_indexable_companies(db, today=today, page=2, per_page=2)
    third = list_indexable_companies(db, today=today, page=3, per_page=2)

    assert (first.total, first.total_pages) == (5, 3)
    assert len(first.items) == 2 and len(second.items) == 2 and len(third.items) == 1
    seen = [item.company.id for item in first.items + second.items + third.items]
    assert len(set(seen)) == 5


def test_rest_endpoints_return_the_company_page_and_reject_unknown_codes(db):
    company = profiled_company(db, "株式会社レスト")
    posting(db, company.name, request_id="rest-1", source_url="https://example.com/rest-1")

    listing = list_companies(db, indexable=True, page=1, per_page=20)
    assert [item["public_code"] for item in listing["items"]] == [company.public_code]
    assert listing["total"] == 1

    detail = company_detail(company.public_code, db)
    assert detail["name"] == company.name
    assert detail["business_summary"] == SUMMARY
    assert detail["description"] == DESCRIPTION
    assert detail["business_areas"] == []
    assert len(detail["current_opportunities"]) == 1

    # Lowercase resolves so an old or hand-typed link still reaches the page.
    assert company_detail(company.public_code.lower(), db)["id"] == company.id

    with pytest.raises(HTTPException) as missing:
        company_detail("ZZZZZZZZ", db)
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as unsupported:
        list_companies(db, indexable=False, page=1, per_page=20)
    assert unsupported.value.status_code == 400
