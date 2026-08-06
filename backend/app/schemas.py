import re
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from pydantic.json_schema import WithJsonSchema

SHORTENER_HOSTS = {
    "bit.ly",
    "goo.gl",
    "t.co",
    "tinyurl.com",
    "is.gd",
    "ow.ly",
    "buff.ly",
}
#: Job boards, aggregators and review sites. A listing there is part of a database someone else
#: built and whose terms forbid automated reuse, so restating it here trades our own compilation
#: for theirs. Only source_url is checked: citing one of these means the record came from the
#: aggregator, while entry_url may legitimately point at a platform the employer chose to use.
#: Extend as new services appear -- a missing host is a gap, never a false rejection.
AGGREGATOR_HOSTS = {
    "asagaku.com",
    "br-campus.jp",
    "career-tasu.jp",
    "careerpark.jp",
    "doda.jp",
    "en-japan.com",
    "gaishishukatsu.com",
    "goodfind.jp",
    "green-japan.com",
    "indeed.com",
    "internshipguide.jp",
    "jobtalk.jp",
    "kyujinbox.com",
    "labbase.jp",
    "levtech.jp",
    "mynavi.jp",
    "offerbox.jp",
    "onecareer.jp",
    "openwork.jp",
    "paiza.jp",
    "rikunabi.com",
    "supporterz.jp",
    "syukatsu-kaigi.jp",
    "type.jp",
    "unistyleinc.com",
    "wantedly.com",
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


def validate_source_host(value: str) -> str:
    host = (urlparse(value).hostname or "").lower()
    # Subdomain match, so job.mynavi.jp is caught by the registrable domain alone.
    if any(host == domain or host.endswith(f".{domain}") for domain in AGGREGATOR_HOSTS):
        raise ValueError(
            "求人サイト・口コミサイトのURLは情報源に指定できません。"
            "企業自身の採用ページなど、一次情報のURLを指定してください"
        )
    return value


def validate_plain_text(value: str | None) -> str | None:
    if value and FORBIDDEN_TEXT.search(value):
        raise ValueError("HTMLタグ、Markdown画像、Markdown形式の外部リンクは使用できません")
    return value


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
SortValue = Literal["deadline", "updated", "created"]


#: Reused by every optional free-text field so the JSON Schema states the "do not guess" rule once.
UNKNOWN_IS_NULL = "推測できない場合はnullにしてください。"
#: The facts in a posting (dates, pay, who may apply) are free to restate, but the wording carrying
#: them belongs to whoever wrote the source page. Stated per field rather than only in the server
#: instructions, because a client that skips the instructions still reads the payload schema.
NO_VERBATIM = (
    "出典の文章をそのまま転記せず、事実だけを自分の言葉で書いてください。"
    "キャッチコピーや宣伝文など、出典独自の表現は使用しません。"
)
#: Postings often name a recruiter or give a direct contact. Neither is needed to describe an
#: opportunity, and no other field in this service identifies an individual.
NO_PERSONAL_DATA = "担当者名などの個人名と、個人宛のメールアドレス・電話番号は含めません。"


class OpportunityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recruitment_status: Annotated[
        RecruitmentStatusValue,
        Field(description="募集の現在状況。判断できない場合は「不明」。", examples=["募集中"]),
    ]
    company_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
        Field(
            description="企業の正式名称。「(株)」などの略記は正規化され、既存企業と自動的に同一視されます。",
            examples=["株式会社リルア"],
        ),
    ]
    industry: Annotated[IndustryValue, Field(description="業界の固定値。", examples=["IT・通信"])]
    sector: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
        Field(
            description=(
                "業種の固定値。指定した業界に属する値だけが有効です。"
                "get_sectorsで業界配下の候補を取得してから指定してください。"
            ),
            examples=["Webサービス"],
        ),
    ]
    event_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
        Field(description="募集・イベントの名称。企業名は含めません。", examples=["サマーインターン2027"]),
    ]
    deadline: Annotated[
        date | None,
        Field(description=f"応募締め切り日（YYYY-MM-DD）。{UNKNOWN_IS_NULL}", examples=["2026-08-31"]),
    ] = None
    event_type: Annotated[EventTypeValue, Field(description="募集の種別。", examples=["インターン"])]
    description: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
        Field(
            description=(
                f"募集内容の説明。{NO_VERBATIM}{NO_PERSONAL_DATA}"
                "HTMLタグ、Markdown画像、Markdownリンクは使用できません。"
            ),
            examples=["プロダクト開発を2週間体験する実務型インターンです。"],
        ),
    ]
    event_format: Annotated[EventFormatValue, Field(description="開催形式。", examples=["オンライン"])]
    location: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None,
        Field(
            description=f"開催地。開催形式がオンラインの場合は必ずnullにしてください。{UNKNOWN_IS_NULL}",
            examples=["東京都渋谷区"],
        ),
    ] = None
    selection_process: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None,
        Field(
            description=f"選考フロー。{NO_VERBATIM}{NO_PERSONAL_DATA}{UNKNOWN_IS_NULL}",
            examples=["書類選考→面接1回"],
        ),
    ] = None
    homepage_url: Annotated[
        str | None,
        Field(description=f"企業または募集のHP（https必須）。{UNKNOWN_IS_NULL}", examples=["https://example.com/"]),
    ] = None
    job_categories: Annotated[
        list[JobCategoryValue],
        Field(min_length=1, description="対象職種の固定値。1件以上、重複不可。", examples=[["ソフトウェアエンジニア"]]),
    ]
    tags: Annotated[
        list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]],
        Field(max_length=10, description="自由記述のキーワード。最大10件、1件20文字以内。", examples=[["長期", "有給"]]),
    ] = []
    event_start_date: Annotated[
        date | None,
        Field(description=f"実施開始日（YYYY-MM-DD）。{UNKNOWN_IS_NULL}", examples=["2026-09-01"]),
    ] = None
    event_end_date: Annotated[
        date | None,
        Field(description=f"実施終了日（YYYY-MM-DD）。実施開始日以降。{UNKNOWN_IS_NULL}", examples=["2026-09-14"]),
    ] = None
    period_note: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None,
        Field(description=f"実施期間の補足。{NO_VERBATIM}{UNKNOWN_IS_NULL}", examples=["全5日間、平日のみ"]),
    ] = None
    requirements: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None,
        Field(
            description=f"応募要件。{NO_VERBATIM}{NO_PERSONAL_DATA}{UNKNOWN_IS_NULL}",
            examples=["Python実務経験があると望ましい"],
        ),
    ] = None
    compensation: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None,
        Field(
            description=f"報酬・待遇。{NO_VERBATIM}{NO_PERSONAL_DATA}{UNKNOWN_IS_NULL}",
            examples=["日給10,000円、交通費支給"],
        ),
    ] = None
    graduation_years: Annotated[
        list[GraduationYearValue],
        Field(min_length=1, description="対象卒業年の固定値。1件以上、重複不可。", examples=[["28卒"]]),
    ]
    degrees: Annotated[
        list[DegreeValue],
        Field(min_length=1, description="対象学位の固定値。1件以上、重複不可。", examples=[["学部", "修士"]]),
    ]
    audience_note: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None,
        Field(
            description=f"対象者の補足。{NO_VERBATIM}{NO_PERSONAL_DATA}{UNKNOWN_IS_NULL}",
            examples=["情報系学部生歓迎"],
        ),
    ] = None
    recruitment_start_date: Annotated[
        date | None,
        Field(description=f"募集開始日（YYYY-MM-DD）。締め切り以前。{UNKNOWN_IS_NULL}", examples=["2026-06-01"]),
    ] = None
    entry_url: Annotated[
        str | None,
        Field(description=f"応募ページのURL（https必須）。{UNKNOWN_IS_NULL}", examples=["https://example.com/entry"]),
    ] = None
    source_url: Annotated[
        str,
        Field(
            description=(
                "情報の出典URL（https必須）。企業自身の採用ページなど、一次情報のURLを指定してください。"
                "求人サイト・就活情報サイト・口コミサイト、短縮URL、IP直指定は使用できません。"
            ),
            examples=["https://example.com/recruit/intern"],
        ),
    ]

    @field_validator("homepage_url", "entry_url", "source_url")
    @classmethod
    def https_urls(cls, value: str | None) -> str | None:
        return validate_https_url(value)

    @field_validator("source_url")
    @classmethod
    def citable_source(cls, value: str) -> str:
        return validate_source_host(value)

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


class CompanyItem(BaseModel):
    id: int
    name: str


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
    public_code: str
    url: str
    recruitment_status: MasterItem
    company: CompanyItem
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


RequestId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=8, max_length=100),
    Field(
        description=(
            "操作ごとにクライアントが発行する一意なID（8〜100文字）。"
            "同じ操作を再試行するときだけ同じ値を使うと、二重登録されずに前回の結果が返ります。"
        ),
        examples=["chatgpt-20260806-0001"],
    ),
]
ClientName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    Field(description="監査ログとレート制限に記録される呼び出し元の名前。", examples=["chatgpt"]),
]


class MCPWriteRequest(OpportunityInput):
    request_id: RequestId
    client_name: ClientName = "mcp-client"


class MCPUpdateRequest(OpportunityUpdate):
    request_id: RequestId
    client_name: ClientName = "mcp-client"


#: MCP tools take the write payload as a plain dict carrying the model's own JSON Schema.
#: A typed parameter would make FastMCP validate the arguments itself and answer with a raw pydantic
#: message, bypassing the structured field/expected/example errors an agent can act on. Publishing the
#: schema separately keeps the enums and descriptions visible while validation stays in our hands.
WritePayload = Annotated[
    dict[str, Any],
    WithJsonSchema(MCPWriteRequest.model_json_schema()),
    Field(description="登録する募集情報の全項目。固定値はget_master_values／get_sectorsのnameを指定します。"),
]
UpdatePayload = Annotated[
    dict[str, Any],
    WithJsonSchema(MCPUpdateRequest.model_json_schema()),
    Field(description="更新後の全項目。部分更新ではないため、変更しない項目も現在値を必ず含めてください。"),
]


class ErrorItem(BaseModel):
    field: str
    received: Any = None
    reason: str
    expected: str | list[str] | None = None
    example: Any = None
    alternative: str | None = None
    #: Set when the failure points at a record that already exists, so the client can update it instead.
    existing: list[dict[str, Any]] | None = None


class ValidationErrorResponse(BaseModel):
    error: str = "validation_failed"
    message: str = "入力内容を修正して再試行してください"
    errors: list[ErrorItem]


class OpportunitySummary(BaseModel):
    """Search-result shape. Free-text fields are trimmed; get_opportunityが全文を返します。"""

    id: str
    public_code: str
    url: str
    company_name: str
    event_name: str
    recruitment_status: str
    event_type: str
    event_format: str
    industry: str
    sector: str
    deadline: date | None
    location: str | None
    description_excerpt: str
    job_categories: list[str]
    graduation_years: list[str]
    degrees: list[str]
    tags: list[str]
    entry_url: str | None
    source_url: str
    updated_at: datetime


class MCPSearchResponse(BaseModel):
    items: list[OpportunitySummary]
    total: int
    page: int
    per_page: int
    total_pages: int


class MCPWriteResponse(BaseModel):
    success: bool
    idempotent_replay: bool
    message: str
    opportunity: OpportunityResponse


class MCPDuplicateResponse(BaseModel):
    message: str
    matches: list[OpportunitySummary]


class MCPValidationResponse(BaseModel):
    valid: bool
    message: str
    duplicates: list[OpportunitySummary]


class MCPSectorsResponse(BaseModel):
    industry: MasterItem
    sectors: list[MasterItem]


class MCPWriteHistoryItem(BaseModel):
    action: str
    request_id: str | None
    client_name: str
    success: bool
    opportunity_id: str | None
    url: str | None
    source_url: str | None
    errors: list[dict[str, Any]] | None
    created_at: datetime


class MCPWriteHistoryResponse(BaseModel):
    items: list[MCPWriteHistoryItem]
