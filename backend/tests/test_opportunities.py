from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event, insert, select
from sqlalchemy.exc import IntegrityError

from app import dates
from app.dates import today_in_tokyo
from app.models import (
    PUBLIC_CODE_ALPHABET,
    PUBLIC_CODE_LENGTH,
    CollectionSource,
    CollectionTarget,
    Company,
    CompanyAlias,
    Opportunity,
    Tag,
)
from app.schemas import OpportunityInput
from app.services import opportunities as opportunities_module
from app.services.normalization import normalize_company_name, normalize_tag
from app.services.opportunities import (
    COMPANY_CANDIDATE_LIMIT,
    DomainValidationError,
    InvalidSearchCursor,
    delete_opportunity,
    find_exact_duplicates,
    find_probable_duplicates,
    find_similar_opportunities,
    get_opportunity,
    get_opportunity_by_public_ref,
    list_opportunities_requiring_review,
    list_stale_opportunities,
    opportunity_input_dict,
    opportunity_patch_changes,
    restore_opportunity,
    search_opportunities,
    update_recruitment_status,
    verify_opportunity,
    write_opportunity,
)
from tests.test_validation import valid_payload


def _create_search_timestamped_opportunities(db, count=3):
    created = []
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    for index in range(count):
        item, _ = write_opportunity(
            db,
            data=OpportunityInput.model_validate(
                valid_payload()
                | {
                    "event_name": f"日時検索{index}",
                    "source_url": f"https://example.com/search-timestamp-{index}",
                }
            ),
            request_id=f"search-timestamp-{index:04d}",
            client_name="pytest",
        )
        item.created_at = base + timedelta(days=index)
        item.updated_at = base + timedelta(days=10 + index)
        created.append(item)
    db.commit()
    return created


def test_create_search_and_idempotent_replay(db):
    data = OpportunityInput.model_validate(valid_payload())
    created, replayed = write_opportunity(
        db,
        data=data,
        request_id="test-request-0001",
        client_name="pytest",
    )
    assert replayed is False

    replay, replayed = write_opportunity(
        db,
        data=data,
        request_id="test-request-0001",
        client_name="pytest",
    )
    assert replayed is True
    assert replay.id == created.id

    result = search_opportunities(db, q="テスト", industry=["industry-01"])
    assert result.total == 1
    assert result.items[0].company.name == "株式会社テスト"
    assert search_opportunities(db, degree=["degree-01"]).total == 1
    assert search_opportunities(db, degree=["degree-06"]).total == 0


def test_search_filters_created_and_updated_at_with_inclusive_boundaries(db):
    items = _create_search_timestamped_opportunities(db)
    base = items[0].created_at
    created_at_mid = items[1].created_at
    updated_at_mid = items[1].updated_at

    assert [
        item.id
        for item in search_opportunities(db, created_at_after=created_at_mid, sort="created").items
    ] == [items[2].id, items[1].id]
    assert [
        item.id
        for item in search_opportunities(db, created_at_before=created_at_mid, sort="created").items
    ] == [items[1].id, items[0].id]
    assert [
        item.id
        for item in search_opportunities(db, updated_at_after=updated_at_mid, sort="created").items
    ] == [items[2].id, items[1].id]
    assert [
        item.id
        for item in search_opportunities(db, updated_at_before=updated_at_mid, sort="created").items
    ] == [items[1].id, items[0].id]

    exact = search_opportunities(
        db,
        created_at_after=created_at_mid,
        created_at_before=created_at_mid,
        updated_at_after=updated_at_mid,
        updated_at_before=updated_at_mid,
        sort="created",
    )
    assert [item.id for item in exact.items] == [items[1].id]
    assert exact.total == 1
    assert items[0].created_at == base


def test_search_cursor_binds_all_timestamp_filters_and_keeps_its_snapshot(db):
    items = _create_search_timestamped_opportunities(db)
    bounds = {
        "created_at_after": items[0].created_at,
        "created_at_before": items[2].created_at,
        "updated_at_after": items[0].updated_at,
        "updated_at_before": items[2].updated_at,
    }
    first_page = search_opportunities(db, **bounds, sort="created", page=None, per_page=1)
    assert first_page.next_cursor is not None

    for field, value in bounds.items():
        with pytest.raises(InvalidSearchCursor):
            search_opportunities(
                db,
                **(bounds | {field: value + timedelta(seconds=1)}),
                sort="created",
                page=None,
                per_page=1,
                cursor=first_page.next_cursor,
            )

    new_item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "event_name": "日時検索スナップショット後",
                "source_url": "https://example.com/search-timestamp-after-snapshot",
            }
        ),
        request_id="search-timestamp-after-snapshot",
        client_name="pytest",
    )
    future = datetime.now(timezone.utc) + timedelta(days=1)  # noqa: UP017 -- tests also support Python 3.10
    new_item.created_at = future
    new_item.updated_at = future
    db.commit()

    seen = [item.id for item in first_page.items]
    totals = [first_page.total]
    cursor = first_page.next_cursor
    while cursor is not None:
        page = search_opportunities(
            db,
            **bounds,
            sort="created",
            page=None,
            per_page=1,
            cursor=cursor,
        )
        seen.extend(item.id for item in page.items)
        totals.append(page.total)
        cursor = page.next_cursor

    assert seen == [item.id for item in reversed(items)]
    assert totals == [len(items)] * len(totals)
    assert new_item.id not in seen


@pytest.mark.parametrize("cursor_mode", [False, True])
def test_empty_first_page_skips_count_query(db, cursor_mode):
    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        result = search_opportunities(
            db,
            q="存在しない企業名",
            page=None if cursor_mode else 1,
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert result.items == []
    assert result.total == 0
    assert not any("count(distinct(opportunities.id))" in statement.lower() for statement in statements)


def test_keyword_search_defaults_to_weighted_relevance(db):
    query = "データサイエンティスト"
    payloads = [
        valid_payload()
        | {
            "company_name": f"株式会社{query}",
            "event_name": "会社説明会",
            "description": "事業内容を紹介します。",
            "job_categories": ["営業"],
            "source_url": "https://example.com/relevance-company",
        },
        valid_payload()
        | {
            "company_name": "株式会社イベント検索",
            "event_name": f"{query}インターン",
            "description": "仕事を体験します。",
            "job_categories": ["営業"],
            "source_url": "https://example.com/relevance-event",
        },
        valid_payload()
        | {
            "company_name": "株式会社職種検索",
            "event_name": "専門職インターン",
            "description": "実務を体験します。",
            "job_categories": [query],
            "source_url": "https://example.com/relevance-job",
        },
        valid_payload()
        | {
            "company_name": "株式会社説明検索",
            "event_name": "技術系インターン",
            "description": f"{query}の実務を体験します。",
            "job_categories": ["営業"],
            "source_url": "https://example.com/relevance-description",
        },
    ]
    for index, payload in enumerate(payloads):
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(payload),
            request_id=f"relevance-ranking-{index:04d}",
            client_name="pytest",
        )

    result = search_opportunities(db, q=query)

    assert [item.company.name for item in result.items] == [
        f"株式会社{query}",
        "株式会社イベント検索",
        "株式会社職種検索",
        "株式会社説明検索",
    ]


def test_explicit_deadline_sort_overrides_relevance(db):
    query = "機械学習"
    later, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": f"株式会社{query}",
                "event_name": f"{query}エンジニア選考",
                "description": f"{query}の仕事です。",
                "deadline": (date.today() + timedelta(days=20)).isoformat(),
                "source_url": "https://example.com/relevance-later",
            }
        ),
        request_id="relevance-deadline-later",
        client_name="pytest",
    )
    sooner, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社締切優先",
                "event_name": f"{query}講座",
                "deadline": (date.today() + timedelta(days=2)).isoformat(),
                "source_url": "https://example.com/relevance-sooner",
            }
        ),
        request_id="relevance-deadline-sooner",
        client_name="pytest",
    )

    assert search_opportunities(db, q=query).items[0].id == later.id
    assert search_opportunities(db, q=query, sort="deadline").items[0].id == sooner.id


def test_relevance_cursor_does_not_skip_tied_scores(db):
    query = "検索順位"
    created = []
    for index in range(3):
        item, _ = write_opportunity(
            db,
            data=OpportunityInput.model_validate(
                valid_payload()
                | {
                    "company_name": f"株式会社カーソル{index}",
                    "event_name": f"{query}インターン",
                    "description": "同じ内容です。",
                    "job_categories": ["営業"],
                    "source_url": f"https://example.com/relevance-cursor-{index}",
                }
            ),
            request_id=f"relevance-cursor-{index:04d}",
            client_name="pytest",
        )
        created.append(item.id)

    seen = []
    cursor = None
    while True:
        result = search_opportunities(db, q=query, page=None, per_page=1, cursor=cursor)
        seen.extend(item.id for item in result.items)
        cursor = result.next_cursor
        if cursor is None:
            break

    assert len(seen) == 3
    assert set(seen) == set(created)


def test_postgresql_trigram_search_recovers_a_typo(db):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("pg_trgm is PostgreSQL-specific")
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社類似検索",
                "event_name": "ソフトウェアエンジニア選考",
                "description": "開発職の募集です。",
                "source_url": "https://example.com/relevance-typo",
            }
        ),
        request_id="relevance-typo-0001",
        client_name="pytest",
    )

    result = search_opportunities(db, q="ソフトウェアエンジニヤ")

    assert [match.id for match in result.items] == [item.id]


def test_public_listing_cutoff_excludes_expired_deadlines_but_keeps_undated(db):
    today = date(2026, 8, 14)
    for index, deadline in enumerate((today - timedelta(days=1), today, None), start=1):
        payload = valid_payload() | {
            "company_name": f"株式会社締切テスト{index}",
            "event_name": f"締切テスト{index}",
            "deadline": deadline.isoformat() if deadline else None,
            "source_url": f"https://example.com/deadline-{index}",
        }
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(payload),
            request_id=f"deadline-filter-{index:04d}",
            client_name="pytest",
        )

    public_result = search_opportunities(db, deadline_on_or_after=today)
    assert public_result.total == 2
    assert {item.deadline for item in public_result.items} == {today, None}

    # Operator searches still need to find expired records so their status can be maintained.
    assert search_opportunities(db).total == 3


def test_today_in_tokyo_changes_at_tokyo_midnight():
    assert today_in_tokyo(datetime(2026, 8, 13, 14, 59, tzinfo=timezone.utc)) == date(2026, 8, 13)  # noqa: UP017
    assert today_in_tokyo(datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)) == date(2026, 8, 14)  # noqa: UP017


def test_company_normalization_reuses_existing_company(db):
    first = OpportunityInput.model_validate(valid_payload())
    first_item, _ = write_opportunity(db, data=first, request_id="normalize-0001", client_name="pytest")

    second_payload = valid_payload() | {"company_name": "(株)テスト", "event_name": "別の募集"}
    second = OpportunityInput.model_validate(second_payload)
    second_item, _ = write_opportunity(db, data=second, request_id="normalize-0002", client_name="pytest")
    assert first_item.company_id == second_item.company_id
    assert second_item.company.name == "株式会社テスト"


def test_company_normalization_collapses_nakaguro_spelling(db):
    """"ディー・エヌ・エー" and "ディーエヌエー" differ only by a syllable separator, so they must
    resolve to one company - not the different script "DeNA", which needs an alias instead."""
    first_payload = valid_payload() | {"company_name": "株式会社ディー・エヌ・エー"}
    first = OpportunityInput.model_validate(first_payload)
    first_item, _ = write_opportunity(db, data=first, request_id="nakaguro-0001", client_name="pytest")

    second_payload = valid_payload() | {"company_name": "ディーエヌエー", "event_name": "別の募集"}
    second = OpportunityInput.model_validate(second_payload)
    second_item, _ = write_opportunity(db, data=second, request_id="nakaguro-0002", client_name="pytest")

    assert first_item.company_id == second_item.company_id
    assert search_opportunities(db, q="ディーエヌエー").total == 2
    matches = find_similar_opportunities(db, company_name="ディーエヌエー")
    assert {item.id for item in matches} == {first_item.id, second_item.id}


def test_company_alias_resolves_search_relevance_and_duplicates(db):
    dena_payload = valid_payload() | {"company_name": "株式会社ディー・エヌ・エー"}
    dena = OpportunityInput.model_validate(dena_payload)
    dena_item, _ = write_opportunity(db, data=dena, request_id="alias-0001", client_name="pytest")
    db.add(
        CompanyAlias(
            company_id=dena_item.company_id, alias="DeNA", normalized_alias=normalize_company_name("DeNA")
        )
    )
    db.flush()

    result = search_opportunities(db, q="DeNA")
    assert result.total == 1
    assert result.items[0].company.name == "株式会社ディー・エヌ・エー"

    matches = find_similar_opportunities(db, company_name="DeNA")
    assert [item.id for item in matches] == [dena_item.id]

    # Writing under the alias must reuse the existing company rather than creating a duplicate one,
    # otherwise the same DeNA opening would silently end up split across two Company rows.
    reused_payload = valid_payload() | {
        "company_name": "DeNA",
        "event_name": "別の募集",
        "source_url": "https://example.com/alias-reuse",
    }
    reused = OpportunityInput.model_validate(reused_payload)
    reused_item, _ = write_opportunity(db, data=reused, request_id="alias-0002", client_name="pytest")
    assert reused_item.company_id == dena_item.company_id


def test_same_company_suggestions_can_be_limited_to_current_openings(db):
    today = date.today()
    current, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload() | {"event_name": "本選考"}),
        request_id="related-current-0001",
        client_name="pytest",
    )
    open_item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "(株)テスト",
                "event_name": "サマーインターン",
                "source_url": "https://example.com/related-open",
            }
        ),
        request_id="related-open-0001",
        client_name="pytest",
    )
    closed_item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "event_name": "終了済み説明会",
                "deadline": (today - timedelta(days=1)).isoformat(),
                "source_url": "https://example.com/related-closed",
            }
        ),
        request_id="related-closed-0001",
        client_name="pytest",
    )

    matches = find_similar_opportunities(
        db,
        company_name="株式会社テスト",
        exclude_id=current.id,
        recruitment_statuses=["募集予定", "募集中", "通年募集"],
        deadline_on_or_after=today,
        limit=3,
    )

    assert [item.id for item in matches] == [open_item.id]
    assert closed_item.id not in {item.id for item in matches}


def test_sector_must_belong_to_industry(db):
    payload = valid_payload() | {"sector": "銀行"}
    data = OpportunityInput.model_validate(payload)
    try:
        write_opportunity(db, data=data, request_id="invalid-sector-01", client_name="pytest")
    except DomainValidationError as exc:
        assert exc.errors[0]["field"] == "業種"
    else:
        raise AssertionError("DomainValidationError was not raised")


def test_ai_sector_can_be_used_under_it_industry(db):
    payload = valid_payload() | {"sector": "AI", "event_name": "AI開発インターン"}
    data = OpportunityInput.model_validate(payload)
    item, replayed = write_opportunity(db, data=data, request_id="ai-sector-0001", client_name="pytest")

    assert replayed is False
    assert item.industry.name == "IT・通信"
    assert item.sector.name == "AI"
    assert item.sector.slug == "sector-1-71"


@pytest.mark.parametrize("industry", ["メーカー", "商社"])
def test_sonota_sector_resolves_to_its_own_industrys_row(db, industry):
    """Regression test: every industry seeds its own "その他" sector row with the same name.

    Resolution must be scoped by industry, or a caller can be told by get_sectors that "その他" is a
    valid choice for their industry, then have add_opportunity reject that exact pair because sector
    resolution silently picked a different industry's "その他" row of the same name.
    """
    from app.services.masters import sectors_for_industry

    _, sectors = sectors_for_industry(db, industry)
    expected_sector = next(item for item in sectors if item.name == "その他")

    payload = valid_payload() | {
        "industry": industry,
        "sector": "その他",
        "event_name": f"{industry}その他インターン",
        "source_url": f"https://example.com/{industry}-sonota",
    }
    data = OpportunityInput.model_validate(payload)
    item, replayed = write_opportunity(db, data=data, request_id=f"sonota-{industry}-0001", client_name="pytest")

    assert replayed is False
    assert item.industry.name == industry
    assert item.sector.name == "その他"
    assert item.sector.id == expected_sector.id
    assert item.sector.industry_id == item.industry.id


def test_child_sector_refines_only_its_selected_parent(db):
    ai_payload = valid_payload() | {"sector": "AI", "event_name": "AI開発インターン"}
    write_opportunity(
        db,
        data=OpportunityInput.model_validate(ai_payload),
        request_id="hierarchy-ai-0001",
        client_name="pytest",
    )
    finance_payload = valid_payload() | {
        "company_name": "株式会社金融テスト",
        "industry": "金融",
        "sector": "銀行",
        "event_name": "金融インターン",
    }
    write_opportunity(
        db,
        data=OpportunityInput.model_validate(finance_payload),
        request_id="hierarchy-finance-0001",
        client_name="pytest",
    )

    result = search_opportunities(
        db,
        industry=["industry-01", "industry-04"],
        sector=["sector-1-71"],
    )
    assert {item.event_name for item in result.items} == {"AI開発インターン", "金融インターン"}


def test_new_opportunity_gets_a_distinct_short_public_code(db):
    first, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="public-code-0001",
        client_name="pytest",
    )
    second_payload = valid_payload() | {"event_name": "二件目の募集"}
    second, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(second_payload),
        request_id="public-code-0002",
        client_name="pytest",
    )

    assert len(first.public_code) == PUBLIC_CODE_LENGTH
    assert set(first.public_code) <= set(PUBLIC_CODE_ALPHABET)
    assert first.public_code != second.public_code


def test_read_path_resolves_both_the_public_code_and_the_uuid(db):
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="public-ref-0001",
        client_name="pytest",
    )

    assert get_opportunity_by_public_ref(db, item.public_code).id == item.id
    assert get_opportunity_by_public_ref(db, item.public_code.lower()).id == item.id
    assert get_opportunity_by_public_ref(db, item.id).id == item.id
    assert get_opportunity_by_public_ref(db, "ZZZZZZZZ") is None


def test_database_rejects_invalid_date_relationship(db):
    company = Company(name="株式会社DB制約テスト", normalized_name="db制約テスト")
    db.add(company)
    db.flush()
    with pytest.raises(IntegrityError):
        db.execute(
            insert(Opportunity).values(
                id="db-constraint-test",
                status_id=2,
                company_id=company.id,
                industry_id=1,
                sector_id=1,
                event_type_id=1,
                event_format_id=2,
                event_name="不正な日付",
                description="終了日が開始日より前です。",
                event_start_date=date(2026, 9, 2),
                event_end_date=date(2026, 9, 1),
                source_url="https://example.com/source",
            )
        )


def test_write_opportunity_records_when_the_official_source_was_confirmed(db):
    data = OpportunityInput.model_validate(valid_payload())
    item, _ = write_opportunity(db, data=data, request_id="checked-at-0001", client_name="pytest")

    assert item.source_checked_at is not None
    assert item.source_checked_at == item.updated_at


def test_updating_an_existing_opportunity_does_not_claim_a_fresh_source_check(db):
    """write != verify: editing a field (e.g. fixing a tag) is not the same claim as having just

    re-read the primary source, so an update/patch must leave source_checked_at exactly as it was
    until a caller separately confirms via verify_opportunity or record_collection_check.
    """
    data = OpportunityInput.model_validate(valid_payload())
    item, _ = write_opportunity(db, data=data, request_id="write-verify-split-0001", client_name="pytest")
    original_checked_at = item.source_checked_at
    original_updated_at = item.updated_at
    assert original_checked_at is not None

    updated, replayed = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload() | {"tags": ["急募"]}),
        request_id="write-verify-split-0002",
        client_name="pytest",
        opportunity_id=item.id,
        expected_updated_at=item.updated_at,
        action="patch",
    )

    assert replayed is False
    assert updated.updated_at > original_updated_at
    assert updated.source_checked_at == original_checked_at


def test_updating_an_existing_opportunity_rejects_collection_target_id(db):
    """collection_target_id only makes sense on a brand-new registration; an update is a plain

    content edit, so passing it is a caller error rather than something to silently ignore.
    """
    data = OpportunityInput.model_validate(valid_payload())
    item, _ = write_opportunity(db, data=data, request_id="write-verify-guard-0001", client_name="pytest")

    with pytest.raises(DomainValidationError) as exc_info:
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(valid_payload() | {"tags": ["急募"]}),
            request_id="write-verify-guard-0002",
            client_name="pytest",
            opportunity_id=item.id,
            expected_updated_at=item.updated_at,
            collection_target_id=1,
        )
    assert exc_info.value.errors[0]["field"] == "情報収集対象ID"


def test_write_opportunity_locks_company_before_checking_duplicates(db):
    """write_opportunity now resolves+row-locks the Company before find_exact_duplicates runs
    (previously the duplicate check ran first, so two concurrent writers for the same company could
    both pass it before either committed). This asserts the reordering didn't change the outcome for
    a single writer: the second write for the same company+event is still rejected as a duplicate.

    A true concurrent-race assertion needs two live DB connections (e.g. Postgres, two threads/
    sessions), which this in-process SQLite fixture cannot exercise - out of scope here.
    """
    data = OpportunityInput.model_validate(valid_payload())
    write_opportunity(db, data=data, request_id="lock-order-0001", client_name="pytest")

    with pytest.raises(DomainValidationError) as exc_info:
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(valid_payload() | {"source_url": "https://example.com/source-2"}),
            request_id="lock-order-0002",
            client_name="pytest",
        )
    assert exc_info.value.errors[0]["field"] == "イベント名"
    assert exc_info.value.errors[0]["existing"]


def test_same_event_name_with_a_different_graduation_year_is_a_probable_not_exact_duplicate(db):
    """Companies routinely reuse one event name across cohorts ("新卒採用エントリー" for both 28卒 and

    29卒). A hard block on company+event_name alone made a genuinely separate posting impossible to
    register without allow_duplicate=true, and upsert_opportunity would silently return the wrong
    existing row instead of creating the new one.
    """
    first = OpportunityInput.model_validate(valid_payload() | {"graduation_years": ["28卒"]})
    first_item, _ = write_opportunity(db, data=first, request_id="grad-split-0001", client_name="pytest")

    second = OpportunityInput.model_validate(
        valid_payload() | {"graduation_years": ["29卒"], "source_url": "https://example.com/grad-split-2"}
    )
    second_item, _ = write_opportunity(db, data=second, request_id="grad-split-0002", client_name="pytest")

    assert second_item.id != first_item.id
    probable = find_probable_duplicates(db, data=second, exclude_id=second_item.id)
    assert [item.id for item in probable] == [first_item.id]


def test_same_event_name_with_a_different_job_category_is_a_probable_not_exact_duplicate(db):
    first = OpportunityInput.model_validate(valid_payload() | {"job_categories": ["ソフトウェアエンジニア"]})
    write_opportunity(db, data=first, request_id="job-split-0001", client_name="pytest")

    second = OpportunityInput.model_validate(
        valid_payload()
        | {"job_categories": ["データサイエンティスト"], "source_url": "https://example.com/job-split-2"}
    )
    second_item, _ = write_opportunity(db, data=second, request_id="job-split-0002", client_name="pytest")
    assert second_item is not None


def test_same_event_name_with_a_different_start_date_is_a_probable_not_exact_duplicate(db):
    first = OpportunityInput.model_validate(valid_payload() | {"event_start_date": "2026-09-01"})
    write_opportunity(db, data=first, request_id="date-split-0001", client_name="pytest")

    second = OpportunityInput.model_validate(
        valid_payload() | {"event_start_date": "2026-10-01", "source_url": "https://example.com/date-split-2"}
    )
    second_item, _ = write_opportunity(db, data=second, request_id="date-split-0002", client_name="pytest")
    assert second_item is not None


def test_unset_identity_fields_do_not_manufacture_a_probable_duplicate(db):
    """A field left unset on either side (e.g. no event_start_date yet) is not evidence of a

    difference, so a genuine repeat registration (same graduation year, job category, and no dates on
    either side) still blocks as an exact duplicate rather than sliding through as merely probable.
    """
    data = OpportunityInput.model_validate(valid_payload())
    write_opportunity(db, data=data, request_id="unset-fields-0001", client_name="pytest")

    with pytest.raises(DomainValidationError) as exc_info:
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(valid_payload() | {"source_url": "https://example.com/unset-fields-2"}),
            request_id="unset-fields-0002",
            client_name="pytest",
        )
    assert exc_info.value.errors[0]["field"] == "イベント名"


def test_update_recruitment_status_uses_optimistic_lock_without_claiming_a_source_check(db):
    data = OpportunityInput.model_validate(valid_payload())
    item, _ = write_opportunity(db, data=data, request_id="checked-at-status-0001", client_name="pytest")
    first_checked_at = item.source_checked_at

    updated, _ = update_recruitment_status(
        db,
        opportunity_id=item.id,
        expected_updated_at=item.updated_at,
        recruitment_status="締切",
        request_id="checked-at-status-0002",
        client_name="pytest",
    )

    assert updated.source_checked_at == first_checked_at
    assert updated.updated_at > first_checked_at

    with pytest.raises(DomainValidationError) as exc_info:
        update_recruitment_status(
            db,
            opportunity_id=item.id,
            expected_updated_at=first_checked_at,
            recruitment_status="募集中",
            request_id="checked-at-status-0003",
            client_name="pytest",
        )
    assert exc_info.value.errors[0]["field"] == "更新前の最終確認日時"


def test_verify_opportunity_refreshes_only_source_checked_at(db):
    data = OpportunityInput.model_validate(valid_payload())
    item, _ = write_opportunity(db, data=data, request_id="checked-at-verify-0001", client_name="pytest")
    original_updated_at = item.updated_at
    checked_at = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10

    verified, replayed = verify_opportunity(
        db,
        opportunity_id=item.id,
        checked_at=checked_at,
        source_url=item.source_url,
        request_id="checked-at-verify-0002",
        client_name="pytest",
    )

    assert replayed is False
    assert verified.source_checked_at == checked_at
    assert verified.updated_at == original_updated_at


def test_list_stale_opportunities_prioritizes_never_checked_then_oldest_first(db):
    fresh, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"company_name": "株式会社新しい確認", "source_url": "https://example.com/stale-fresh"}
        ),
        request_id="stale-fresh-0001",
        client_name="pytest",
    )
    stale, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"company_name": "株式会社古い確認", "source_url": "https://example.com/stale-old"}
        ),
        request_id="stale-old-0001",
        client_name="pytest",
    )
    stale.source_checked_at = datetime.now(timezone.utc) - timedelta(days=40)  # noqa: UP017 -- local Python is 3.10
    never_checked, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"company_name": "株式会社未確認", "source_url": "https://example.com/stale-never"}
        ),
        request_id="stale-never-0001",
        client_name="pytest",
    )
    never_checked.source_checked_at = None
    db.commit()

    assert search_opportunities(db, q="株式会社新しい確認").total == 1  # sanity: fresh really was written
    stale_results = list_stale_opportunities(db, days=7)
    stale_ids = [item.id for item in stale_results]

    assert fresh.id not in stale_ids
    assert stale_ids.index(never_checked.id) < stale_ids.index(stale.id)


def test_reconfirmation_queues_exclude_closed_and_unknown_statuses(db):
    items = {}
    for index, status in enumerate(("募集予定", "募集中", "通年募集", "締切", "不明"), start=1):
        item, _ = write_opportunity(
            db,
            data=OpportunityInput.model_validate(
                valid_payload()
                | {
                    "recruitment_status": status,
                    "company_name": f"株式会社保守対象{index}",
                    "event_name": f"保守対象{index}",
                    "source_url": f"https://example.com/reconfirmation-status-{index}",
                }
            ),
            request_id=f"reconfirmation-status-{index:04d}",
            client_name="pytest",
        )
        item.source_checked_at = datetime.now(timezone.utc) - timedelta(days=40)  # noqa: UP017
        items[status] = item
    db.commit()

    expected = {items[status].id for status in ("募集予定", "募集中", "通年募集")}
    assert {item.id for item in list_stale_opportunities(db, days=7)} == expected
    reviews = list_opportunities_requiring_review(db, days=7)
    assert {review.opportunity.id for review in reviews} == expected


def test_review_queue_includes_fresh_date_status_conflicts_before_stale_sources(db):
    stale, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"company_name": "株式会社通常確認", "source_url": "https://example.com/review-stale"}
        ),
        request_id="review-stale-0001",
        client_name="pytest",
    )
    stale.source_checked_at = datetime.now(timezone.utc) - timedelta(days=40)  # noqa: UP017 -- local Python is 3.10
    today = today_in_tokyo()
    conflict, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社期限矛盾",
                "event_name": "矛盾テスト",
                "deadline": (today - timedelta(days=1)).isoformat(),
                "event_end_date": (today - timedelta(days=2)).isoformat(),
                "source_url": "https://example.com/review-conflict",
            }
        ),
        request_id="review-conflict-0001",
        client_name="pytest",
    )
    db.commit()

    reviews = list_opportunities_requiring_review(db, days=7)
    by_id = {review.opportunity.id: review for review in reviews}

    assert reviews[0].opportunity.id == conflict.id
    assert by_id[conflict.id].reasons == ["deadline_passed_while_open", "event_ended_while_open"]
    assert by_id[stale.id].reasons == ["source_not_checked_recently"]


def test_keyword_search_treats_like_wildcards_literally(db):
    """"%" and "_" are LIKE metacharacters, and neither PostgreSQL nor SQLite escapes them by default.

    Unescaped, a query of "%" matched every row - and every row was then reported back to the user as
    a keyword hit - while "_" matched any single character and the pattern stopped being indexable.
    """
    write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="like-escape-0001",
        client_name="pytest",
    )
    literal, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社100%達成",
                "event_name": "内定率100%_説明会",
                "source_url": "https://example.com/like-escape",
            }
        ),
        request_id="like-escape-0002",
        client_name="pytest",
    )

    for wildcard in ("%", "_"):
        result = search_opportunities(db, q=wildcard)
        assert [item.id for item in result.items] == [literal.id]
    assert [item.id for item in search_opportunities(db, q="100%_説明").items] == [literal.id]
    assert search_opportunities(db, q="存在しない%").total == 0


def test_status_update_deadline_bound_survives_a_leap_day(db, monkeypatch):
    """The companion to the schemas.py bound: here the same replace(year=+5) was a plain 500."""
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="leap-status-0001",
        client_name="pytest",
    )
    monkeypatch.setattr(dates, "today_in_tokyo", lambda *_args, **_kwargs: date(2028, 2, 29))

    updated, _ = update_recruitment_status(
        db,
        opportunity_id=item.id,
        expected_updated_at=item.updated_at,
        recruitment_status="募集中",
        deadline=date(2029, 4, 1),
        request_id="leap-status-0002",
        client_name="pytest",
    )
    assert updated.deadline == date(2029, 4, 1)

    with pytest.raises(DomainValidationError) as exc_info:
        update_recruitment_status(
            db,
            opportunity_id=item.id,
            expected_updated_at=updated.updated_at,
            recruitment_status="募集中",
            deadline=date(2033, 3, 1),
            request_id="leap-status-0003",
            client_name="pytest",
        )
    assert exc_info.value.errors[0]["reason"] == "許容範囲外の日付です"


def test_deadline_and_clear_deadline_cannot_be_combined(db):
    """The two arguments express opposite intents, so silently preferring one hides a caller bug."""
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="clear-deadline-0001",
        client_name="pytest",
    )

    with pytest.raises(DomainValidationError) as exc_info:
        update_recruitment_status(
            db,
            opportunity_id=item.id,
            expected_updated_at=item.updated_at,
            recruitment_status="締切",
            deadline=date(2027, 3, 1),
            clear_deadline=True,
            request_id="clear-deadline-0002",
            client_name="pytest",
        )
    assert exc_info.value.errors[0]["reason"] == "deadlineとclear_deadlineは同時に指定できません"
    assert item.deadline is not None  # neither intent was applied


def _monitor_company(db, company_id: int, *, url: str) -> CollectionTarget:
    """Attach a minimal collection target so the company gets an official-source allowlist."""
    target = CollectionTarget(company_id=company_id, is_active=True)
    target.sources.append(CollectionSource(source_type="recruit", url=url, is_active=True))
    db.add(target)
    db.flush()
    return target


def test_a_company_with_no_active_sources_falls_back_instead_of_locking_out_writes(db):
    """An allowlist with no entries rejected every URL, so deactivating the last collection source

    silently locked the company out of every future registration - with "expected: []" as the only
    explanation an agent ever saw. No active source means no curated trust anchor, which is the same
    situation as an unmonitored company: the legacy aggregator denylist is the check that applies.
    """
    first, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="empty-allowlist-0001",
        client_name="pytest",
    )
    target = _monitor_company(db, first.company_id, url="https://example.com/recruit")
    outside = valid_payload() | {
        "event_name": "別の募集",
        "source_url": "https://unrelated.example/posting",
    }

    with pytest.raises(DomainValidationError) as exc_info:
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(outside),
            request_id="empty-allowlist-0002",
            client_name="pytest",
        )
    assert "allowlist" in exc_info.value.errors[0]["reason"]

    target.sources[0].is_active = False
    db.flush()

    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(outside),
        request_id="empty-allowlist-0003",
        client_name="pytest",
    )
    assert item.source_url == "https://unrelated.example/posting"


def test_a_deactivated_collection_target_stops_enforcing_its_allowlist(db):
    """The lookup here did not filter on is_active, unlike _auto_matched_collection_target, so a

    deactivated target kept enforcing an allowlist that nobody was maintaining any more.
    """
    first, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="inactive-target-0001",
        client_name="pytest",
    )
    target = _monitor_company(db, first.company_id, url="https://example.com/recruit")
    target.is_active = False
    db.flush()

    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload() | {"event_name": "別の募集", "source_url": "https://unrelated.example/posting"}
        ),
        request_id="inactive-target-0002",
        client_name="pytest",
    )
    assert item.source_url == "https://unrelated.example/posting"


def test_restore_still_works_when_the_company_has_no_active_sources(db):
    """restore_opportunity re-checks the allowlist, so an empty one made a soft-deleted record

    permanently unrecoverable - and close_expired physically deletes it 30 days later.
    """
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="restore-allowlist-0001",
        client_name="pytest",
    )
    target = _monitor_company(db, item.company_id, url=item.source_url)
    delete_opportunity(
        db,
        opportunity_id=item.id,
        expected_updated_at=item.updated_at,
        request_id="restore-allowlist-0002",
        client_name="pytest",
    )
    target.sources[0].is_active = False
    db.flush()

    restored, replayed = restore_opportunity(
        db,
        opportunity_id=item.id,
        request_id="restore-allowlist-0003",
        client_name="pytest",
    )
    assert replayed is False
    assert restored["id"] == item.id
    assert get_opportunity(db, item.id) is not None


def test_an_update_cannot_turn_a_record_into_an_exact_duplicate(db):
    """The exact-duplicate check only ran on create, so an update could make a record identical to

    another live one with neither an error nor a warning: find_probable_duplicates reports only the
    matches that were downgraded to probable, never exact ones.
    """
    first, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="update-duplicate-0001",
        client_name="pytest",
    )
    second_payload = valid_payload() | {
        "event_name": "別の募集",
        "source_url": "https://example.com/update-duplicate-2",
    }
    second, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(second_payload),
        request_id="update-duplicate-0002",
        client_name="pytest",
    )

    with pytest.raises(DomainValidationError) as exc_info:
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(second_payload | {"event_name": first.event_name}),
            request_id="update-duplicate-0003",
            client_name="pytest",
            opportunity_id=second.id,
            expected_updated_at=second.updated_at,
        )
    assert exc_info.value.errors[0]["field"] == "イベント名"
    assert [entry["id"] for entry in exc_info.value.errors[0]["existing"]] == [first.id]

    # An ordinary edit keeps the record's own event name, so it must not collide with its own row.
    updated, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(second_payload | {"description": "内容を更新しました。"}),
        request_id="update-duplicate-0004",
        client_name="pytest",
        opportunity_id=second.id,
        expected_updated_at=second.updated_at,
    )
    assert updated.description == "内容を更新しました。"


def test_patch_idempotency_hash_ignores_the_timezone_offset(db):
    """The same instant sent back in a different offset is the same request, so a retry has to

    replay - not be rejected as "same request_id, different content" like an unrelated operation.
    """
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="offset-hash-0001",
        client_name="pytest",
    )
    expected = item.updated_at
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    patch_data = OpportunityInput.model_validate(valid_payload() | {"tags": ["急募"]})

    patched, replayed = write_opportunity(
        db,
        data=patch_data,
        request_id="offset-hash-0002",
        client_name="pytest",
        opportunity_id=item.id,
        expected_updated_at=expected,
        action="patch",
    )
    assert replayed is False

    retried, replayed = write_opportunity(
        db,
        data=patch_data,
        request_id="offset-hash-0002",
        client_name="pytest",
        opportunity_id=item.id,
        expected_updated_at=expected.astimezone(timezone(timedelta(hours=9))),
        action="patch",
    )
    assert replayed is True
    assert retried.id == patched.id


def test_reordering_a_list_field_is_not_a_patch_change(db):
    """Stored order is canonical and caller order is arbitrary, so comparing them positionally

    reported a change for a pure reorder - bumping updated_at and invalidating every other client's
    expected_updated_at without anything having actually changed.
    """
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "job_categories": ["ソフトウェアエンジニア", "営業"],
                "tags": ["急募", "交通費支給"],
            }
        ),
        request_id="reorder-patch-0001",
        client_name="pytest",
    )

    reordered = OpportunityInput.model_validate(
        opportunity_input_dict(item)
        | {"job_categories": ["営業", "ソフトウェアエンジニア"], "tags": ["交通費支給", "急募"]}
    )
    assert opportunity_patch_changes(item, reordered) == []

    dropped = OpportunityInput.model_validate(opportunity_input_dict(item) | {"tags": ["急募"]})
    assert [entry["field"] for entry in opportunity_patch_changes(item, dropped)] == ["tags"]


def test_same_company_lookup_applies_its_limit_in_sql(db):
    """GET /opportunities/{id}/same-company needs three rows, and find_exact_duplicates runs on the

    add_opportunity hot path. Both used to materialize the company's entire history, eager relations
    included, and slice it in Python.
    """
    created = []
    for index in range(4):
        item, _ = write_opportunity(
            db,
            data=OpportunityInput.model_validate(
                valid_payload()
                | {
                    "event_name": f"会社説明会{index}",
                    "source_url": f"https://example.com/company-limit-{index}",
                }
            ),
            request_id=f"company-limit-{index:04d}",
            client_name="pytest",
        )
        created.append(item.id)

    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        matches = find_similar_opportunities(db, company_name="株式会社テスト", exclude_id=created[0], limit=2)
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert len(matches) == 2
    company_select = next(statement for statement in statements if "FROM opportunities" in statement)
    assert "LIMIT" in company_select.upper()


def test_reading_one_opportunity_does_not_fan_out_one_query_per_relation(db):
    """The six master relations are many-to-one, so an OUTER JOIN returns them with the row itself.

    selectinload made a single-row read cost six extra round trips on top of the four selectin
    collections the model already declares.
    """
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="eager-shape-0001",
        client_name="pytest",
    )
    db.expunge_all()

    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        fetched = get_opportunity(db, item.id)
        assert fetched is not None
        assert fetched.status.name == "募集中"
        assert fetched.company.name == "株式会社テスト"
        assert fetched.sector.name == "Webサービス"
        assert [value.name for value in fetched.job_categories] == ["ソフトウェアエンジニア"]
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    master_tables = ("recruitment_statuses", "companies", "industries", "sectors", "event_types", "event_formats")
    row_query = statements[0]
    assert all(f"JOIN {table} " in row_query for table in master_tables)
    assert [
        statement
        for statement in statements[1:]
        if any(f"FROM {table} " in statement for table in master_tables)
    ] == []


def test_verify_opportunity_takes_the_row_lock(db, monkeypatch):
    """The "newer than the stored source_checked_at" check is an unprotected read-modify-write

    without the lock, so two concurrent verifies can both pass it and the older check time can land
    last. The real race needs two live connections (Postgres, two sessions), which this in-process
    SQLite fixture cannot exercise, so this asserts the locking read is the one being used.
    """
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="verify-lock-0001",
        client_name="pytest",
    )
    locked: list[str] = []
    locked_read = opportunities_module.get_opportunity_for_update

    def spy(session, opportunity_id, **kwargs):
        locked.append(opportunity_id)
        return locked_read(session, opportunity_id, **kwargs)

    monkeypatch.setattr(opportunities_module, "get_opportunity_for_update", spy)
    monkeypatch.setattr(
        opportunities_module,
        "get_opportunity",
        lambda *_args, **_kwargs: pytest.fail("verify_opportunity must use the locking read"),
    )

    verified, _ = verify_opportunity(
        db,
        opportunity_id=item.id,
        checked_at=datetime.now(timezone.utc),  # noqa: UP017 -- tests also support Python 3.10
        source_url=item.source_url,
        request_id="verify-lock-0002",
        client_name="pytest",
    )
    assert locked == [item.id]
    assert verified.source_checked_at is not None


def test_tag_creation_recovers_from_a_concurrent_insert_of_the_same_tag(db, monkeypatch):
    """Two writes introducing the same brand-new tag both miss the lookup, and the one that loses

    tags.normalized_name UNIQUE has to adopt the winner's row instead of turning an ordinary write
    into a 500. The concurrent commit is simulated by inserting the winner immediately before our
    own INSERT is attempted, which is the window the savepoint exists to survive.
    """
    item, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload()),
        request_id="tag-race-0001",
        client_name="pytest",
    )
    normalized = normalize_tag("急募")
    real_begin_nested = db.begin_nested
    winner_ids: list[int] = []

    def racing_begin_nested():
        if not winner_ids:
            winner = Tag(name="急募", normalized_name=normalized)
            db.add(winner)
            db.flush()
            winner_ids.append(winner.id)
        return real_begin_nested()

    monkeypatch.setattr(db, "begin_nested", racing_begin_nested)
    updated, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload() | {"tags": ["急募"]}),
        request_id="tag-race-0002",
        client_name="pytest",
        opportunity_id=item.id,
        expected_updated_at=item.updated_at,
        action="patch",
    )

    assert [tag.id for tag in updated.tags] == winner_ids
    assert len(db.scalars(select(Tag).where(Tag.normalized_name == normalized)).all()) == 1


def test_exact_duplicate_detection_is_not_capped_by_the_company_candidate_limit(db):
    """A company past the candidate cap must still have its re-registrations blocked.

    The "other postings by this company" helper caps how many rows it materializes, and the exact
    duplicate check used to share that cap. A company with more live postings than the cap could then
    re-register an older posting verbatim: the older row had been pushed out of the most-recently-
    updated window, so nothing matched and the duplicate was created without an error or a warning.
    """
    company = "株式会社大量募集"
    oldest, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": company,
                "event_name": "最古のイベント",
                "source_url": "https://example.com/bulk-oldest",
            }
        ),
        request_id="bulk-oldest-1",
        client_name="pytest",
    )
    for index in range(COMPANY_CANDIDATE_LIMIT + 5):
        write_opportunity(
            db,
            data=OpportunityInput.model_validate(
                valid_payload()
                | {
                    "company_name": company,
                    "event_name": f"別イベント{index}",
                    "source_url": f"https://example.com/bulk-{index}",
                }
            ),
            request_id=f"bulk-{index}",
            client_name="pytest",
        )
    db.commit()

    assert [item.id for item in find_exact_duplicates(db, company_name=company, event_name="最古のイベント")] == [
        oldest.id
    ]
