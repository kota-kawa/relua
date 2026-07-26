import re
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

SHORTENER_HOSTS = {
    "bit.ly",
    "goo.gl",
    "t.co",
    "tinyurl.com",
    "is.gd",
    "ow.ly",
    "buff.ly",
}
FORBIDDEN_TEXT = re.compile(r"<[^>]+>|!\[[^]]*]\([^)]*\)|\[[^]]+]\(https?://[^)]+\)", re.IGNORECASE)


def validate_https_url(value: str | None) -> str | None:
    if value is None:
        return value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or len(value) > 2048:
        raise ValueError("https形式でホスト名を含む2048文字以内のURLを指定してください")
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        raise ValueError("localhostまたはIPアドレスを直接指定するURLは使用できません")
    if host in SHORTENER_HOSTS:
        raise ValueError("短縮URLは使用できません。元のURLを指定してください")
    return value


def validate_plain_text(value: str | None) -> str | None:
    if value and FORBIDDEN_TEXT.search(value):
        raise ValueError("HTMLタグ、Markdown画像、Markdown形式の外部リンクは使用できません")
    return value


RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RecruitmentStatusValue = Literal["募集予定", "募集中", "締切", "通年募集", "不明"]
IndustryValue = Literal[
    "IT・通信", "メーカー", "商社", "金融", "コンサル・シンクタンク", "広告・メディア",
    "建設・不動産", "運輸・物流", "医療・製薬", "エネルギー・インフラ", "小売・流通",
    "サービス", "教育", "公務・団体",
]
EventTypeValue = Literal["インターン", "本選考", "説明会・セミナー", "エントリー受付", "イベント", "その他"]
EventFormatValue = Literal["オンライン", "対面", "ハイブリッド", "不明"]
JobCategoryValue = Literal[
    "ソフトウェアエンジニア", "データサイエンティスト", "機械学習エンジニア", "インフラ・SRE",
    "セキュリティ", "研究開発", "生産技術", "品質保証", "営業", "マーケティング", "企画・経営企画",
    "人事", "経理・財務", "法務", "コンサルタント", "デザイナー", "総合職", "事務職", "その他",
]
GraduationYearValue = Literal["26卒", "27卒", "28卒", "29卒", "30卒", "学年不問"]
DegreeValue = Literal["学部", "修士", "博士", "高専", "専門", "不問"]


class OpportunityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recruitment_status: RecruitmentStatusValue
    company_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    industry: IndustryValue
    sector: RequiredText
    event_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    deadline: date | None = None
    event_type: EventTypeValue
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    event_format: EventFormatValue
    location: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    selection_process: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    homepage_url: str | None = None
    job_categories: Annotated[list[JobCategoryValue], Field(min_length=1)]
    tags: Annotated[list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]], Field(max_length=10)] = []
    event_start_date: date | None = None
    event_end_date: date | None = None
    period_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    requirements: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    compensation: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    graduation_years: Annotated[list[GraduationYearValue], Field(min_length=1)]
    degrees: Annotated[list[DegreeValue], Field(min_length=1)]
    audience_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    recruitment_start_date: date | None = None
    entry_url: str | None = None
    source_url: str

    @field_validator("homepage_url", "entry_url", "source_url")
    @classmethod
    def https_urls(cls, value: str | None) -> str | None:
        return validate_https_url(value)

    @field_validator(
        "event_name",
        "description",
        "location",
        "selection_process",
        "period_note",
        "requirements",
        "compensation",
        "audience_note",
    )
    @classmethod
    def plain_text(cls, value: str | None) -> str | None:
        return validate_plain_text(value)

    @field_validator("job_categories", "tags", "graduation_years", "degrees")
    @classmethod
    def no_duplicates(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("同じ値を重複して指定できません")
        return values

    @model_validator(mode="after")
    def related_fields(self) -> "OpportunityInput":
        if self.event_start_date and self.event_end_date and self.event_end_date < self.event_start_date:
            raise ValueError("実施終了日は実施開始日以降にしてください")
        if self.recruitment_start_date and self.deadline and self.deadline < self.recruitment_start_date:
            raise ValueError("締め切りは募集開始日以降にしてください")
        if self.event_format == "オンライン" and self.location:
            raise ValueError("開催形式がオンラインの場合、開催地はnullにしてください")
        limit = date.today().replace(year=date.today().year + 5)
        for field_name in ("deadline", "event_start_date", "event_end_date", "recruitment_start_date"):
            value = getattr(self, field_name)
            if value and not (date(2000, 1, 1) <= value <= limit):
                raise ValueError(f"{field_name}は2000-01-01から実行日の5年後までにしてください")
        return self


class OpportunityUpdate(OpportunityInput):
    """MVP updates are full replacements to preserve all-field validation."""


class MasterItem(BaseModel):
    id: int
    slug: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class SectorItem(MasterItem):
    industry_id: int


class MastersResponse(BaseModel):
    recruitment_statuses: list[MasterItem]
    industries: list[MasterItem]
    sectors: list[SectorItem]
    event_types: list[MasterItem]
    event_formats: list[MasterItem]
    job_categories: list[MasterItem]
    graduation_years: list[MasterItem]
    degrees: list[MasterItem]


class OpportunityResponse(BaseModel):
    id: str
    recruitment_status: MasterItem
    company: dict[str, Any]
    industry: MasterItem
    sector: MasterItem
    event_name: str
    deadline: date | None
    event_type: MasterItem
    description: str
    event_format: MasterItem
    location: str | None
    selection_process: str | None
    homepage_url: str | None
    job_categories: list[MasterItem]
    tags: list[str]
    event_start_date: date | None
    event_end_date: date | None
    period_note: str | None
    requirements: str | None
    compensation: str | None
    graduation_years: list[MasterItem]
    degrees: list[MasterItem]
    audience_note: str | None
    recruitment_start_date: date | None
    entry_url: str | None
    source_url: str
    created_at: datetime
    updated_at: datetime


class OpportunityListResponse(BaseModel):
    items: list[OpportunityResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class MCPWriteRequest(OpportunityInput):
    request_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=100)]
    client_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] = "mcp-client"


class MCPUpdateRequest(OpportunityUpdate):
    request_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=100)]
    client_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] = "mcp-client"


class ErrorItem(BaseModel):
    field: str
    received: Any = None
    reason: str
    expected: str | list[str] | None = None
    example: Any = None
    alternative: str | None = None


class ValidationErrorResponse(BaseModel):
    error: str = "validation_failed"
    message: str = "入力内容を修正して再試行してください"
    errors: list[ErrorItem]
