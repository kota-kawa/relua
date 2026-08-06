from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas import OpportunityInput


def valid_payload() -> dict:
    return {
        "recruitment_status": "募集中",
        "company_name": "株式会社テスト",
        "industry": "IT・通信",
        "sector": "Webサービス",
        "event_name": "開発インターン",
        "deadline": (date.today() + timedelta(days=30)).isoformat(),
        "event_type": "インターン",
        "description": "プロダクト開発を体験します。",
        "event_format": "オンライン",
        "location": None,
        "job_categories": ["ソフトウェアエンジニア"],
        "graduation_years": ["28卒"],
        "degrees": ["学部"],
        "source_url": "https://example.com/source",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("deadline", "2026/08/31"),
        ("source_url", "http://example.com/source"),
        ("source_url", "https://bit.ly/sample"),
        ("description", "<script>alert(1)</script>"),
        ("industry", "AI業界"),
    ],
)
def test_invalid_input_is_rejected(field: str, value: str):
    payload = valid_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        OpportunityInput.model_validate(payload)


@pytest.mark.parametrize(
    "url",
    [
        "https://mynavi.jp/intern/123",
        "https://job.mynavi.jp/27/pc/search/corp123/outline.html",  # subdomain
        "https://job.rikunabi.com/2028/company/r123456/",
        "https://www.wantedly.com/projects/123456",
        "https://en-japan.com/desc_123/",
        "https://openwork.jp/company_answer.php?m_id=a1",  # review site, not a posting at all
    ],
)
def test_aggregator_is_rejected_as_source(url: str):
    payload = valid_payload()
    payload["source_url"] = url
    with pytest.raises(ValidationError, match="一次情報"):
        OpportunityInput.model_validate(payload)


def test_aggregator_is_still_allowed_as_entry_url():
    """The employer may run applications through a platform; only the citation must be first-party."""
    payload = valid_payload()
    payload["entry_url"] = "https://www.wantedly.com/projects/123456"
    assert OpportunityInput.model_validate(payload).entry_url.startswith("https://www.wantedly.com/")


def test_company_domain_resembling_an_aggregator_is_accepted():
    """endswith matching must respect the dot, so mynavi.jp does not swallow notmynavi.jp."""
    payload = valid_payload()
    payload["source_url"] = "https://notmynavi.jp/recruit"
    assert OpportunityInput.model_validate(payload).source_url == "https://notmynavi.jp/recruit"


def test_online_event_rejects_location():
    payload = valid_payload()
    payload["location"] = "東京都"
    with pytest.raises(ValidationError, match="オンライン"):
        OpportunityInput.model_validate(payload)


def test_valid_input_accepts_strict_values():
    item = OpportunityInput.model_validate(valid_payload())
    assert item.company_name == "株式会社テスト"
    assert item.source_url == "https://example.com/source"
